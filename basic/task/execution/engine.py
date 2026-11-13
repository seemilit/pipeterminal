"""Non-interactive execution with bounded output, deadlines and no automatic retry."""
import base64
import codecs
import json
import locale
import os
import posixpath
import queue
import re
import shlex
import shutil
import signal
import stat
import subprocess
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from uuid import uuid4
from common.i18n import tr
from .schema import effective_kind, validate


class ExecutionError(RuntimeError):
    pass


class CommandExitError(ExecutionError):
    pass


class UnknownRemoteState(ExecutionError):
    pass


def interpreter_path(name):
    candidates = {"cmd": [os.environ.get("COMSPEC", "cmd.exe")], "powershell": ["pwsh", "powershell"], "bash": ["bash"], "sh": ["sh"]}.get(name, [])
    if name in {"git_bash", "bash", "sh"} and os.name == "nt":
        git = shutil.which("git")
        roots = list(Path(git).resolve().parents)[:3] if git else []
        roots += [Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git",
                  Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Programs/Git"]
        filename = "sh.exe" if name == "sh" else "bash.exe"
        native = [str(root / folder / filename) for root in roots for folder in ("bin", "usr/bin")]
        candidates = native + candidates
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            if os.name == "nt" and name in {"bash", "sh", "git_bash"}:
                windows = Path(os.environ.get("SystemRoot", "C:/Windows")).resolve()
                # WSL launchers do not accept the native Windows script paths used here.
                if Path(found).resolve().parent in {windows / "System32", windows / "Sysnative", windows / "SysWOW64"}:
                    continue
            return found
    raise ExecutionError(tr("找不到所选解释器：{0}", name))


def command_text(interpreter, text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if interpreter in {"bash", "git_bash"}:
        return "#!/usr/bin/env bash\nset -e\nset -o pipefail\n" + text + "\n"
    if interpreter == "sh":
        return "#!/bin/sh\nset -e\n" + text + "\n"
    if interpreter == "powershell":
        commands = []
        for line in text.splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                commands.append("$global:LASTEXITCODE = 0\n. {\n" + line + "\n}\nif ($LASTEXITCODE) { exit $LASTEXITCODE }")
        return "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)\n$OutputEncoding = [Console]::OutputEncoding\n$ErrorActionPreference = 'Stop'\n$PSNativeCommandUseErrorActionPreference = $true\n" + "\n".join(commands) + "\n"
    commands = ["@echo off", "chcp 65001 >nul"]
    for line in text.splitlines():
        if not line.strip() or re.match(r"(?i)^\s*(?:rem(?:\s|$)|::)", line):
            continue
        # CALL is needed for another batch file to return to the next command.
        if re.match(r'(?i)^\s*(?:"[^"\r\n]+\.(?:bat|cmd)"|[^\s"]+\.(?:bat|cmd))(?=\s|$)', line):
            line = "call " + line
        commands.extend((line, 'if not "%errorlevel%"=="0" exit /b %errorlevel%'))
    commands.append("exit /b 0")
    return "\r\n".join(commands) + "\r\n"


def output_encoding(interpreter, executable, command=False):
    if interpreter in {"bash", "sh", "git_bash"} or command or Path(executable).stem.lower() == "pwsh":
        return "utf-8-sig"
    if os.name == "nt":
        import ctypes
        codepage = ctypes.windll.kernel32.GetOEMCP()
        if codepage:
            return "cp" + str(codepage)
    return locale.getpreferredencoding(False)


def powershell_argv(executable, *arguments):
    # Applies to this child process only; machine and user policies are unchanged.
    return [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-OutputFormat", "Text", *arguments]


def bash_login_command(command):
    return "if [ -f ~/.bashrc ]; then . ~/.bashrc; fi; " + command


def local_argv(executable, interpreter, path, args):
    if interpreter == "cmd":
        # No CALL re-expansion and no user-supplied arguments in this first version.
        if any(char in str(path) for char in '%!"\r\n'):
            raise ExecutionError(tr("CMD 脚本路径包含不支持的特殊字符"))
        return subprocess.list2cmdline([executable]) + ' /d /s /c ""' + str(path) + '""'
    if interpreter == "powershell":
        return powershell_argv(executable, "-File", str(path), *args)
    return [executable, str(path).replace("\\", "/"), *args]


class ExecutionEngine:
    def __init__(self, services, log, stop, *, output_decoder=None):
        self.services, self.log, self.stop = services, log, stop
        self._output_decoder = output_decoder

    def execute(self, kind, properties):
        values = validate(kind, properties)
        kind = effective_kind(kind, values)
        started = time.monotonic()
        if kind.startswith("REMOTE"):
            self._remote(kind, values)
        else:
            self._local(kind, values)
        self.log(tr("执行完成，耗时 {0} 秒", round(time.monotonic() - started, 2)))

    def _local(self, kind, values):
        executable = interpreter_path(values["INTERPRETER"])
        self.log(tr("解释器：{0}", executable))
        cwd = Path(values["WORKING_DIRECTORY"]).expanduser() if values["WORKING_DIRECTORY"].strip() else Path.home()
        cwd = cwd.resolve()
        if not cwd.is_dir():
            raise ExecutionError(tr("工作目录不存在"))
        shell_environment = None
        if os.name == "nt" and values["INTERPRETER"] in {"sh", "bash", "git_bash"}:
            parent = Path(executable).parent
            tools = [folder for folder in (parent, parent.parent / "usr/bin") if folder.is_dir()]
            shell_environment = {
                "PATH": os.pathsep.join([*(str(folder) for folder in tools), os.environ.get("PATH", "")]),
                "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
            }
        if values["INTERPRETER"] == "powershell" and kind.endswith("COMMAND"):
            if self.stop.is_set():
                raise ExecutionError(tr("执行已停止"))
            text = command_text("powershell", values["COMMAND"])
            encoded = base64.b64encode(text.encode("utf-16-le")).decode("ascii")
            self.log(tr("工作目录：{0}", cwd))
            self._process(powershell_argv(executable, "-EncodedCommand", encoded), cwd, int(values["TIMEOUT"]), encoding="utf-8-sig")
            return
        with TemporaryDirectory(prefix="pipeterminal-command-") as temporary:
            inline = kind.endswith("SCRIPT") and "SCRIPT_CONTENT" in values
            path = Path(values["SCRIPT_PATH"]).expanduser() if kind.endswith("SCRIPT") and not inline else Path(temporary) / {"cmd": "command.cmd", "powershell": "command.ps1"}.get(values["INTERPRETER"], "command.sh")
            path = (path if path.is_absolute() else cwd / path).resolve()
            if kind.endswith("COMMAND") or inline:
                text = values["SCRIPT_CONTENT"].lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n") if inline else command_text(values["INTERPRETER"], values["COMMAND"])
                if inline and values["INTERPRETER"] == "cmd":
                    text = text.replace("\n", "\r\n")
                encoding = "utf-8-sig" if values["INTERPRETER"] == "powershell" else "utf-8"
                path.write_text(text, encoding=encoding, newline="")
            if not path.is_file():
                raise ExecutionError(tr("脚本文件不存在"))
            if kind.endswith("SCRIPT") and values["INTERPRETER"] in {"bash", "git_bash", "sh"}:
                with path.open("rb") as handle:
                    sample = handle.read(65536)
                if sample.startswith((codecs.BOM_UTF8, codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) or b"\r\n" in sample:
                    raise ExecutionError(tr("Shell 脚本请保存为 UTF-8 无 BOM、LF 换行；原文件未修改"))
            if self.stop.is_set():
                raise ExecutionError(tr("执行已停止"))
            args = local_argv(executable, values["INTERPRETER"], path, json.loads(values["ARGUMENTS"]))
            if shell_environment is not None:
                shell_path = Path(executable).absolute()
                bash = executable
                if values["INTERPRETER"] == "sh":
                    sibling = shell_path.with_name("bash.exe")
                    bash = str(sibling) if sibling.is_file() else interpreter_path("bash")
                # Login profiles may change directories. Restore the task's cwd and pass arguments verbatim.
                # Keep Bash alive as the parent for taskkill /T on Windows.
                command = bash_login_command('cd -- "$1" || exit; shift; "$@"; exit "$?"')
                args = [bash, "-lc", command, "pipeterminal", cwd.as_posix(), shell_path.as_posix(), *args[1:]]
            self.log(tr("工作目录：{0}", cwd))
            utf8_script = False
            if values["INTERPRETER"] in {"cmd", "powershell"} and kind.endswith("SCRIPT"):
                with path.open("rb") as handle:
                    sample = handle.read(65536)
                if values["INTERPRETER"] == "cmd":
                    utf8_script = bool(re.search(rb"(?im)^\s*@?chcp\s+65001\b", sample))
                else:
                    utf8_script = b"[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)" in sample
            self._process(args, cwd, int(values["TIMEOUT"]), shell_environment, encoding=output_encoding(values["INTERPRETER"], executable, kind.endswith("COMMAND") or utf8_script))

    def _process(self, argv, cwd, timeout, extra_env=None, encoding=None):
        environment = os.environ.copy()
        environment.update(extra_env or {})
        process = subprocess.Popen(argv, cwd=cwd, env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), start_new_session=os.name != "nt")
        output = queue.Queue(maxsize=64)
        drained = Event()
        def read():
            try:
                while True:
                    chunk = process.stdout.read1(8192)
                    if not chunk:
                        break
                    while True:
                        try:
                            output.put(chunk, timeout=.1)
                            break
                        except queue.Full:
                            if drained.is_set():
                                return
            finally:
                process.stdout.close()
        reader = Thread(target=read, daemon=True)
        reader.start()
        decoder = self._output_decoder or codecs.getincrementaldecoder(encoding or locale.getpreferredencoding(False))(errors="replace")
        deadline = time.monotonic() + timeout if timeout else None
        try:
            while reader.is_alive() or not output.empty() or process.poll() is None:
                if self.stop.is_set() or (deadline is not None and time.monotonic() >= deadline):
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=True,
                                       capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
                    else:
                        os.killpg(process.pid, signal.SIGKILL)
                    raise ExecutionError(tr("执行已停止或超时；请检查命令产生的外部影响"))
                try:
                    data = output.get(timeout=.1)
                except queue.Empty:
                    continue
                text = decoder.decode(data)
                if text:
                    self.log(text)
                    time.sleep(.01)
            tail = decoder.decode(b"", final=True)
            if tail:
                self.log(tail)
            code = process.wait(timeout=5)
            self.log(tr("退出码：{0}", code))
            if code:
                raise CommandExitError(tr("命令执行失败，退出码：{0}", code))
        finally:
            drained.set()
            if process.poll() is None:
                process.kill()
            reader.join(timeout=1)

    def _remote(self, kind, values):
        client = self.services.connection(values["SERVER"], self.log)
        if self.stop.is_set():
            raise ExecutionError(tr("执行已停止"))
        try:
            sftp = client.open_sftp()
        except Exception:
            self.services.discard(client)
            if self.stop.is_set():
                raise ExecutionError(tr("执行已停止"))
            # Safe to reconnect here: no user command has been submitted.
            client = self.services.connection(values["SERVER"], self.log)
            sftp = client.open_sftp()
        temporary = None
        files = []
        channel = None
        uncertain = False
        try:
            home = sftp.normalize(".")
            requested = values["WORKING_DIRECTORY"].strip()
            cwd = home if not requested or requested == "~" else posixpath.join(home, requested[2:]) if requested.startswith("~/") else requested
            if not cwd.startswith("/"):
                cwd = posixpath.join(home, cwd)
            if not stat.S_ISDIR(sftp.stat(cwd).st_mode):
                raise ExecutionError(tr("工作目录不存在"))
            interpreter = values["INTERPRETER"]
            # Check fixed executables without running the user's command.
            self._remote_check(client, (
                'for executable in sh bash setsid; do '
                'command -v "$executable" >/dev/null || '
                '{ printf "%s: command not found\\n" "$executable" >&2; exit 127; }; done'
            ))
            inline = kind.endswith("SCRIPT") and "SCRIPT_CONTENT" in values
            existing = kind.endswith("SCRIPT") and not inline and values.get("SCRIPT_SOURCE", "remote") == "remote"
            if existing:
                path = values["SCRIPT_PATH"]
                path = posixpath.join(home, path[2:]) if path.startswith("~/") else path
                path = path if path.startswith("/") else posixpath.join(cwd, path)
                if not stat.S_ISREG(sftp.stat(path).st_mode):
                    raise ExecutionError(tr("脚本文件不存在"))
            else:
                if inline:
                    text = values["SCRIPT_CONTENT"].lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
                elif kind.endswith("SCRIPT"):
                    local = Path(values["SCRIPT_PATH"]).expanduser().resolve()
                    if not local.is_file() or local.stat().st_size > 16 * 1024 * 1024:
                        raise ExecutionError(tr("本地脚本不存在或超过 16 MiB"))
                    text = local.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
                else:
                    text = command_text(interpreter, values["COMMAND"])
            staging_path = "/tmp/pipeterminal-task-" + uuid4().hex
            sftp.mkdir(staging_path, mode=0o700)
            temporary = staging_path
            if not existing:
                path = temporary + "/script.sh"
                files.append(path)
                with sftp.open(path, "wb") as handle:
                    handle.write(text.encode("utf-8"))
                sftp.chmod(path, 0o600)
            pid_path = temporary + "/pid"
            files.append(pid_path)
            invocation = shlex.join([interpreter, path, *json.loads(values["ARGUMENTS"])])
            login_command = bash_login_command(
                "cd -- " + shlex.quote(cwd) + " || exit; exec " + invocation
            )
            # Record the group leader before Bash starts loading its profiles.
            job = "echo $$ > " + shlex.quote(pid_path) + " || exit; exec bash -lc " + shlex.quote(login_command)
            # With job control disabled, this background child is not a process-group
            # leader: setsid can exec without forking, and sh can wait for its exit
            # status even on older servers that do not support setsid --wait.
            launcher = "set +m; setsid sh -c " + shlex.quote(job) + ' </dev/null & task_pid=$!; wait "$task_pid"'
            command = "exec sh -c " + shlex.quote(launcher)
            channel = client.get_transport().open_session(timeout=20)
            channel.set_combine_stderr(True)
            channel.settimeout(1)
            if self.stop.is_set():
                raise ExecutionError(tr("执行已停止"))
            # Once submitted, a failed connection must never cause an automatic retry.
            try:
                channel.exec_command(command)
                decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                timeout = int(values["TIMEOUT"])
                deadline = time.monotonic() + timeout if timeout else None
                while True:
                    if channel.exit_status_ready() and not channel.recv_ready():
                        break
                    if self.stop.is_set() or (deadline is not None and time.monotonic() >= deadline):
                        self._stop_remote(client, sftp, pid_path)
                    if channel.recv_ready():
                        self.log(decoder.decode(channel.recv(16384)))
                        time.sleep(.01)
                    elif not client.get_transport().is_active() or channel.closed:
                        raise UnknownRemoteState(tr("远程连接中断，执行状态未知；不会自动重试"))
                    else:
                        time.sleep(.05)
                self.log(decoder.decode(b"", final=True))
                code = channel.recv_exit_status()
                if code == -1:
                    raise UnknownRemoteState(tr("远程连接中断，执行状态未知；不会自动重试"))
                self.log(tr("退出码：{0}", code))
                if code:
                    raise CommandExitError(tr("命令执行失败，退出码：{0}", code))
            except ExecutionError:
                raise
            except Exception as exc:
                raise UnknownRemoteState(tr("远程连接中断，执行状态未知；不会自动重试")) from exc
        except UnknownRemoteState:
            uncertain = True
            raise
        finally:
            if channel is not None:
                channel.close()
            if temporary and not uncertain:
                try:
                    for path in files:
                        try:
                            sftp.remove(path)
                        except FileNotFoundError:
                            pass
                    sftp.rmdir(temporary)
                except Exception:
                    self.log(tr("临时目录未清理：{0}", temporary))
            elif temporary:
                self.log(tr("保留临时目录：{0}", temporary))
            sftp.close()

    def _stop_remote(self, client, sftp, pid_path):
        try:
            sftp.get_channel().settimeout(5)
            deadline = time.monotonic() + 1
            while True:
                try:
                    with sftp.open(pid_path) as handle:
                        pid = handle.read(32).strip()
                except FileNotFoundError:
                    pid = b""
                if pid.isdigit() and int(pid) > 1:
                    break
                if time.monotonic() >= deadline:
                    raise ValueError("Remote process group ID is unavailable")
                time.sleep(.05)
            group = "-" + pid.decode("ascii")
            self._remote_check(client, (
                "test -x /bin/kill || exit 127; "
                f"/bin/kill -TERM -- {group} 2>/dev/null || true; sleep 0.5; "
                f"if /bin/kill -0 -- {group} 2>/dev/null; then /bin/kill -KILL -- {group}; fi"
            ), cancel_on_stop=False)
        except Exception as exc:
            raise UnknownRemoteState(tr("无法确认远程进程已停止，请检查服务器")) from exc
        raise ExecutionError(tr("已向远程进程组发送停止信号；脱离进程组的服务需要手动检查"))

    def _remote_check(self, client, command, *, cancel_on_stop=True):
        if cancel_on_stop and self.stop.is_set():
            raise ExecutionError(tr("执行已停止"))
        channel = client.get_transport().open_session(timeout=20)
        channel.settimeout(20)
        try:
            channel.exec_command(command)
            deadline = time.monotonic() + 20
            output = bytearray()
            while not channel.exit_status_ready() or channel.recv_ready() or channel.recv_stderr_ready():
                for ready, receive in ((channel.recv_ready, channel.recv), (channel.recv_stderr_ready, channel.recv_stderr)):
                    if ready():
                        data = receive(4096)
                        if len(output) < 65536:
                            output.extend(data[:65536-len(output)])
                if (cancel_on_stop and self.stop.is_set()) or time.monotonic() > deadline:
                    raise ExecutionError(tr("配置检查已停止或超时"))
                time.sleep(.02)
            if channel.recv_exit_status():
                raise ExecutionError(tr("远程配置检查失败：{0}", output.decode("utf-8", "replace")))
        finally:
            channel.close()
