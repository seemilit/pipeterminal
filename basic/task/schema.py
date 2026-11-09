"""Unified workflow catalog; existing Git type identifiers remain unchanged."""
from .git.schema import STEP_LABELS as GIT_LABELS, FIELD_LABELS as GIT_FIELDS
from .execution.schema import STEP_LABELS as EXECUTION_LABELS, FIELD_LABELS as EXECUTION_FIELDS
from .upload import STEP_LABELS as UPLOAD_LABELS, FIELD_LABELS as UPLOAD_FIELDS
from .health import FIELD_LABELS as HEALTH_FIELDS
STEP_LABELS = {**GIT_LABELS, **EXECUTION_LABELS, **UPLOAD_LABELS, "WAIT": "等待", "HEALTH_CHECK": "健康检查", "OPEN_SHELL": "唤醒服务器"}
FIELD_LABELS = {**GIT_FIELDS, **EXECUTION_FIELDS, **UPLOAD_FIELDS, "SECONDS": "等待时间（秒）", **HEALTH_FIELDS, "SHELL_COMMAND": "脚本内容"}
CATEGORIES = {"Git": tuple(kind for kind in GIT_LABELS if kind != "MAVEN_BUILD"), "构建": ("MAVEN_BUILD",), "命令与脚本": ("LOCAL_SCRIPT", "REMOTE_SCRIPT", "OPEN_SHELL"), "文件上传": tuple(UPLOAD_LABELS), "流程控制": ("WAIT", "HEALTH_CHECK")}
