"""Local Maven packaging as an independent workflow step."""
import codecs
import os
import shlex
import shutil
from pathlib import Path
from common.i18n import tr
from ..execution.engine import ExecutionEngine


def validate_build(properties):
    project = properties.get("PROJECT_PATH", "")
    timeout = properties.get("BUILD_TIMEOUT", "600")
    if not isinstance(project, str) or not project.strip() or any(ord(char) < 32 for char in project):
        raise ValueError(tr("请填写项目目录"))
    path = Path(project).expanduser()
    if not path.is_absolute():
        raise ValueError(tr("请填写项目目录的完整路径"))
    try:
        seconds = int(timeout)
    except (TypeError, ValueError):
        raise ValueError(tr("打包超时必须为 1～86400 秒")) from None
    if not 1 <= seconds <= 86400:
        raise ValueError(tr("打包超时必须为 1～86400 秒"))
    name = properties.get("ARTIFACT_NAME", "artifact")
    if not isinstance(name, str) or not name.strip() or any(ord(char) < 32 for char in name):
        raise ValueError(tr("请填写产物名称"))
    from ..jar_artifact import jar_patterns
    filters = properties.get("JAR_FILTER", "")
    if not isinstance(filters, str):
        raise ValueError(tr("请填写有效的上传参数"))
    jar_patterns(filters)
    return path, seconds


class MavenOutputDecoder:
    """Decode UTF-8 Maven lines and legacy Java's Windows ANSI diagnostics."""

    def __init__(self):
        self._pending = b""

    def decode(self, data, final=False):
        self._pending += data
        parts = []
        while self._pending:
            newline = self._pending.find(b"\n", 0, 65536)
            complete = newline >= 0 or (final and len(self._pending) <= 65536)
            if not complete and len(self._pending) <= 65536:
                break
            length = newline + 1 if newline >= 0 else min(len(self._pending), 65536)
            chunk = self._pending[:length]
            decoder = codecs.getincrementaldecoder("utf-8-sig")(errors="strict")
            try:
                text = decoder.decode(chunk, final=complete)
            except UnicodeDecodeError:
                decoder = codecs.getincrementaldecoder("mbcs")(errors="replace")
                text = decoder.decode(chunk, final=complete)
            pending, _state = decoder.getstate()
            self._pending = pending + self._pending[length:]
            parts.append(text)
        return "".join(parts)


class MavenBuild:
    def __init__(self, services, log, stop):
        self.services, self.log, self.stop = services, log, stop

    def execute(self, properties):
        project, timeout = validate_build(properties)
        project = project.resolve()
        if not project.is_dir() or not (project / "pom.xml").is_file():
            raise ValueError(tr("项目目录中未找到 pom.xml：{0}", str(project)))
        windows = os.name == "nt"
        wrapper = project / ("mvnw.cmd" if windows else "mvnw")
        executable = str(wrapper) if wrapper.is_file() else (shutil.which("mvn.cmd") or shutil.which("mvn")) if windows else shutil.which("mvn")
        if not executable:
            raise ValueError(tr("未找到 Maven，请配置 Maven Wrapper 或 Maven PATH"))
        if windows:
            if any(char in executable for char in '%!"\r\n'):
                raise ValueError(tr("Maven 路径包含不支持的字符"))
            command = 'call "' + executable + '" clean package'
        else:
            command = ("sh " if wrapper.is_file() else "") + shlex.quote(executable) + " clean package"
        self.log(tr("开始打包：{0}", str(project)))
        decoder = MavenOutputDecoder() if windows else None
        ExecutionEngine(self.services, self.log, self.stop, output_decoder=decoder).execute("LOCAL_COMMAND", {
            "INTERPRETER": "cmd" if windows else "sh", "WORKING_DIRECTORY": str(project),
            "COMMAND": command, "TIMEOUT": str(timeout),
        })
        from ..jar_artifact import detect_jars
        artifacts = tuple(detect_jars(project, self.stop, properties.get("JAR_FILTER", "")))
        self.log(tr("自动识别 JAR：{0}", "\n".join(str(path) for path in artifacts)))
        self.log(tr("打包完成：{0}", str(project)))
        return artifacts
