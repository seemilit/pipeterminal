"""Execution steps share the existing task document format."""
import json
import os
from common.i18n import tr

STEP_LABELS = {"LOCAL_COMMAND": "Win 命令/脚本", "LOCAL_SCRIPT": "Win 命令/脚本", "REMOTE_COMMAND": "Linux 命令/脚本", "REMOTE_SCRIPT": "Linux 命令/脚本"}
FIELD_LABELS = {"EXECUTION_MODE": "执行方式", "WORKING_DIRECTORY": "工作目录", "COMMAND": "执行命令", "SCRIPT_CONTENT": "脚本内容", "ARGUMENTS": "脚本参数", "INTERPRETER": "解释器", "SERVER": "服务器配置", "TIMEOUT": "超时（秒）"}
DEFAULTS = {"INTERPRETER": "powershell", "WORKING_DIRECTORY": "", "COMMAND": "", "ARGUMENTS": "[]", "SERVER": "", "TIMEOUT": "0"}
CHOICES = {
    "EXECUTION_MODE": {"command": "命令", "script": "脚本"},
    "INTERPRETER": {"cmd": "CMD", "powershell": "PowerShell", "git_bash": "Git Bash", "bash": "Bash", "sh": "Sh"},
}

def defaults(kind):
    result = dict(DEFAULTS)
    result["EXECUTION_MODE"] = "script" if kind.endswith("SCRIPT") else "command"
    if kind.startswith("REMOTE"):
        result["INTERPRETER"] = "bash"
    return result

def effective_kind(kind, properties):
    mode = properties.get("EXECUTION_MODE", "script" if kind.endswith("SCRIPT") else "command")
    if mode not in {"command", "script"}:
        raise ValueError(tr("执行方式无效"))
    return ("REMOTE_" if kind.startswith("REMOTE") else "LOCAL_") + mode.upper()


def working_directory_required(kind):
    return os.name == "nt" and kind.startswith("LOCAL")


def validate(kind, properties):
    if kind not in STEP_LABELS:
        raise ValueError(tr("不支持的执行步骤"))
    kind = effective_kind(kind, properties)
    values = defaults(kind)
    values.update(properties)
    values.pop("FAILURE_POLICY", None)
    values.pop("CLEANUP", None)
    if kind.endswith("COMMAND"):
        values["ARGUMENTS"] = "[]"
    if any(not isinstance(value, str) or "\0" in value for value in values.values()):
        raise ValueError(tr("执行参数必须是文本且不能包含空字符"))
    if working_directory_required(kind) and not values["WORKING_DIRECTORY"].strip():
        raise ValueError(tr("请填写：{0}", tr(FIELD_LABELS["WORKING_DIRECTORY"])))
    try:
        timeout = int(values["TIMEOUT"])
        args = json.loads(values["ARGUMENTS"])
    except (ValueError, TypeError):
        raise ValueError(tr("超时必须是整数，脚本参数必须是字符串数组")) from None
    if not 0 <= timeout <= 86400 or not isinstance(args, list) or any(not isinstance(arg, str) or "\0" in arg or "\n" in arg or "\r" in arg for arg in args):
        raise ValueError(tr("超时范围为 0～86400 秒，参数不能包含换行"))
    for key in CHOICES:
        if values[key] not in CHOICES[key]:
            raise ValueError(tr("执行选项无效：{0}", tr(FIELD_LABELS.get(key, "脚本内容"))))
    if kind.startswith("REMOTE") and (not values["SERVER"] or values["INTERPRETER"] not in {"bash", "sh"}):
        raise ValueError(tr("请选择服务器配置和远程解释器"))
    key = "COMMAND" if kind.endswith("COMMAND") else "SCRIPT_CONTENT" if "SCRIPT_CONTENT" in values else "SCRIPT_PATH"
    if not values.get(key, "").strip():
        raise ValueError(tr("请填写：{0}", tr(FIELD_LABELS.get(key, "脚本内容"))))
    if values["INTERPRETER"] == "cmd" and kind.endswith("SCRIPT") and args:
        raise ValueError(tr("CMD 脚本暂不支持附加参数"))
    return values
