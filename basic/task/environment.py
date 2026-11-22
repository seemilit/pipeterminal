"""Check dependencies available to workflow nodes without running commands."""

import os
import shutil
from pathlib import Path

from common.i18n import tr

from .execution.engine import ExecutionError, interpreter_path
from .execution.schema import CHOICES
from .git.build import maven_launcher
from .git.schema import STEP_FIELDS


def local_interpreter():
    for name in ("powershell", "cmd", "git_bash", "bash", "sh"):
        try:
            interpreter_path(name)
        except ExecutionError:
            continue
        return name
    return None


def environment_issue(kind, properties=None, *, servers=None):
    if kind in STEP_FIELDS and kind != "MAVEN_BUILD" and not shutil.which("git"):
        return tr("未找到 Git，请先安装并配置 PATH")
    if kind == "MAVEN_BUILD":
        java = "java.exe" if os.name == "nt" else "java"
        java_home = os.environ.get("JAVA_HOME", "").strip('"')
        java_path = str(Path(java_home) / "bin" / java) if java_home else java
        if not shutil.which(java_path):
            return tr("未找到 Java，请配置 JAVA_HOME 或 PATH")
        # The project may provide its own Wrapper. Check after it is selected.
        if properties is not None:
            project = Path(properties["PROJECT_PATH"]).expanduser().resolve()
            if not maven_launcher(project):
                return tr("未找到 Maven，请配置 Maven Wrapper 或 Maven PATH")
    if kind in {"LOCAL_COMMAND", "LOCAL_SCRIPT"}:
        if properties is None:
            if local_interpreter() is None:
                return tr("未找到可用的本地命令解释器")
        else:
            name = properties.get("INTERPRETER", "powershell")
            try:
                interpreter_path(name)
            except ExecutionError:
                return tr("找不到所选解释器：{0}", tr(CHOICES["INTERPRETER"].get(name, name)))
    if kind.startswith("REMOTE_") and servers is not None:
        if properties is None and not servers:
            return tr("请先添加服务器配置")
        if properties is not None and properties.get("SERVER") not in servers:
            return tr("服务器配置不存在：{0}", properties.get("SERVER", ""))
    return None
