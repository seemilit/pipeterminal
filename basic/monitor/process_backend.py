"""Worker-only Linux process operations on one captured connection."""

import shlex

from basic.sftp.backend import check_cancelled, open_sftp
from basic.shell.commands import AuxiliaryCommandRunner
from common.i18n import tr


def _guard(process):
    if process.pid <= 1 or not process.start_time.isascii() or not process.start_time.isdigit():
        raise ValueError(tr("无法确认进程身份，请刷新后重试"))
    changed = shlex.quote(str(tr("进程已退出或已改变，未执行操作")))
    protected = shlex.quote(str(tr("不能操作当前 SSH 连接依赖的进程")))
    return f"""set -f
pid={process.pid}
expected={shlex.quote(process.start_time)}
fail() {{ printf '%s\\n' "$*" >&2; exit 1; }}
start_id() {{
    [ -r "/proc/$pid/stat" ] || return 1
    IFS= read -r value < "/proc/$pid/stat" || return 1
    value=${{value##*) }}
    set -- $value
    [ "$1" != Z ] || return 1
    printf '%s' "${{20}}"
}}
changed() {{ fail {changed}; }}
[ "$(start_id)" = "$expected" ] || changed
ancestor=$$
while [ "$ancestor" -gt 1 ] 2>/dev/null; do
    [ "$ancestor" != "$pid" ] || fail {protected}
    ancestor=$(ps -o ppid= -p "$ancestor" | tr -d ' ')
done
"""


def _execute(context, cancel, script, timeout):
    runner = AuxiliaryCommandRunner(context.transport, context.connection_stop)
    # The shell parses the complete group before executing any mutation.
    # A truncated upload cannot execute the stop half of a restart script.
    return runner.run("/bin/sh -s", cancel, timeout=timeout,
                      stdin_data=("{\n" + script + "\n}\n").encode("utf-8"))


def stop_process(context, cancel, process):
    script = _guard(process) + '[ "$(start_id)" = "$expected" ] || changed\nkill -TERM "$pid"\n'
    _execute(context, cancel, script, 15)
    return str(tr("已发送停止指令，请刷新确认服务状态"))


def capture_process(context, cancel, process):
    _guard(process)
    with open_sftp(context, cancel) as sftp:
        def read(name, limit=1024 * 1024):
            check_cancelled(context, cancel)
            with sftp.open(f"/proc/{process.pid}/{name}", "rb") as stream:
                chunks, total = [], 0
                while True:
                    check_cancelled(context, cancel)
                    chunk = stream.read(min(32768, limit + 1 - total))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                    if total > limit:
                        raise ValueError(tr("进程启动信息过大，未停止原进程"))
            return b"".join(chunks)

        def identity():
            fields = read("stat", 65536).rsplit(b")", 1)[1].split()
            if fields[0] == b"Z" or fields[19].decode("ascii") != process.start_time:
                raise ValueError(tr("进程已退出或已改变，未执行操作"))

        identity()
        raw = read("cmdline")
        if not raw.endswith(b"\0"):
            raise ValueError(tr("无法记录完整启动命令，未停止原进程"))
        args = [part.decode("utf-8") for part in raw[:-1].split(b"\0")]
        if not args or not args[0] or " ".join(args) != process.command:
            raise ValueError(tr("进程命令已变化，请刷新后重试"))
        directory = sftp.readlink(f"/proc/{process.pid}/cwd")
        executable = sftp.readlink(f"/proc/{process.pid}/exe")
        if not directory.startswith("/") or not executable.startswith("/") or executable.endswith(" (deleted)"):
            raise ValueError(tr("原程序或工作目录不可用，未停止原进程"))
        status = dict(line.split(b":", 1) for line in read("status").splitlines() if b":" in line)
        environment = [part.decode("utf-8") for part in read("environ").split(b"\0") if b"=" in part]
        units = sorted({part for line in read("cgroup").decode("utf-8").splitlines()
                        for part in line.split(":", 2)[-1].split("/") if part.endswith(".service")
                        and part not in {"ssh.service", "sshd.service"} and not part.startswith("user@")})
        identity()
        return {
            "args": args, "directory": directory, "executable": executable,
            "environment": environment, "units": units,
            "uid": int(status[b"Uid"].split()[1]), "gid": int(status[b"Gid"].split()[1]),
            "groups": [int(value) for value in status.get(b"Groups", b"").split()],
            "umask": int(status.get(b"Umask", b"0022").strip(), 8),
        }


def restart_process(context, cancel, process):
    snapshot = capture_process(context, cancel, process)
    environment = dict(value.split("=", 1) for value in snapshot["environment"])
    if environment.get("LISTEN_FDS", "0") not in {"", "0"} or environment.get("SUPERVISOR_ENABLED") or "PM2_HOME" in environment:
        raise ValueError(tr("进程由管理器托管，请使用管理器重启；未停止原进程"))
    directory = shlex.quote(snapshot["directory"])
    executable = shlex.quote(snapshot["executable"])
    launch = f"cd -- {directory} && umask {snapshot['umask']:03o} && exec " + shlex.join(
        ["env", "-i", "--", *snapshot["environment"], snapshot["executable"], *snapshot["args"][1:]],
    )
    groups = ("--groups " + shlex.quote(",".join(map(str, snapshot["groups"])))) if snapshot["groups"] else "--clear-groups"
    preflight = shlex.quote(f"test -d {directory} && test -x {directory} && test -x {executable}")
    managed = shlex.quote(str(tr("无法确认服务自动重启策略，请使用管理器重启；未停止原进程")))
    unavailable = shlex.quote(str(tr("缺少启动条件，未停止原进程")))
    still_running = shlex.quote(str(tr("原进程尚未退出，未强杀或重复启动")))
    failed = shlex.quote(str(tr("原进程已停止，新命令启动失败，请检查日志：")))
    submitted = shlex.quote(str(tr("已尝试按原命令启动，请检查服务状态和日志：")))
    script = _guard(process) + f"""
for unit in {shlex.join(snapshot['units'])}; do
    policy=$(systemctl show --property=Restart -- "$unit" 2>/dev/null) || fail {managed}
    [ "$policy" = 'Restart=no' ] || fail {managed}
done
command -v nohup >/dev/null 2>&1 || fail {unavailable}
set --
if [ "$(id -u)" != "{snapshot['uid']}" ] || [ "$(id -g)" != "{snapshot['gid']}" ]; then
    [ "$(id -u)" = 0 ] || fail {unavailable}
    command -v setpriv >/dev/null 2>&1 || fail {unavailable}
    set -- setpriv --reuid {snapshot['uid']} --regid {snapshot['gid']} {groups}
fi
"$@" /bin/sh -c {preflight} || fail {unavailable}
logfile=$(umask 077; mktemp /tmp/pipeterminal-restart-{process.pid}.XXXXXX) || fail {unavailable}
exec 3>>"$logfile" 4>&3
if [ -f "/proc/$pid/fd/1" ]; then exec 3>>"/proc/$pid/fd/1"; fi
if [ -f "/proc/$pid/fd/2" ]; then exec 4>>"/proc/$pid/fd/2"; fi
[ "$(start_id)" = "$expected" ] || changed
kill -TERM "$pid" || fail {unavailable}
count=0
while [ "$(start_id)" = "$expected" ]; do
    [ "$count" -lt 15 ] || fail {still_running}
    sleep 1
    count=$((count + 1))
done
nohup "$@" /bin/sh -c {shlex.quote(launch)} < /dev/null >&3 2>&4 &
new_pid=$!
sleep 1
if ! kill -0 "$new_pid" 2>/dev/null; then
    wait "$new_pid"
    code=$?
    [ "$code" = 0 ] || fail "${{code}}: "{failed}"$logfile"
fi
printf '%s %s (PID %s)\\n' {submitted} "$logfile" "$new_pid"
"""
    check_cancelled(context, cancel)
    return _execute(context, cancel, script, 45).strip()
