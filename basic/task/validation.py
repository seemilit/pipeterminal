"""Shared preflight validation for the editor and background runner."""
from copy import deepcopy
from common.i18n import tr
from .schema import STEP_LABELS
from .git.schema import POLICIES, STEP_FIELDS
from .git.build import validate_build
from .execution.schema import STEP_LABELS as EXECUTION_LABELS, validate
from .upload import STEP_LABELS as UPLOAD_LABELS, validate_upload
from .health import validate_health
from .shell_panel import validate_shell_panel
from .wait import wait_seconds


def _preceding_build(steps, index, project):
    for candidate in range(index - 1, -1, -1):
        step = steps[candidate]
        if step["type"] == "MAVEN_BUILD":
            properties = step.get("properties", {})
            if not project or properties.get("PROJECT_PATH", "") == project:
                return candidate
    return None


def prepare_workflow(document, server_store=None, *, indexes=None, check_connections=True, predecessors=None, artifacts=None):
    steps = deepcopy(document.get("steps", []))
    issues, groups = [], {}
    selected = set(range(len(steps)) if indexes is None else indexes)
    if not selected or not selected.issubset(range(len(steps))):
        return steps, [(-1, str(tr("任务为空或包含尚未支持的流程")))]
    partial = len(selected) != len(steps)
    selected_builds = {
        steps[index].get("properties", {}).get("ARTIFACT_NAME", "artifact").strip()
        for index in selected if steps[index].get("type") == "MAVEN_BUILD"
        and isinstance(steps[index].get("properties", {}).get("ARTIFACT_NAME", "artifact"), str)
    }
    checked_servers = {}
    servers = set(server_store.list_names()) if server_store is not None else None
    order = range(len(steps)) if indexes is None else indexes
    ancestors = {}
    for index in order:
        if predecessors is not None:
            parents = predecessors[index]
            ancestors[index] = set(parents).union(*(ancestors[parent] for parent in parents))
        step = steps[index]
        try:
            kind = step["type"]
            properties = step.get("properties", {})
            if kind not in STEP_LABELS:
                raise ValueError(tr("任务为空或包含尚未支持的流程"))
            if check_connections and index + 1 in selected and step.get("connection_disabled", False):
                issues.append((index, str(tr("此节点与下一步之间的连线已断开"))))
            if kind == "MAVEN_BUILD":
                validate_build(properties)
                name = properties.setdefault("ARTIFACT_NAME", "artifact").strip()
                if name in groups:
                    raise ValueError(tr("产物名称重复：{0}", name))
                properties["ARTIFACT_NAME"] = name
                groups[name] = (properties.get("PROJECT_PATH", ""), index)
            elif kind in UPLOAD_LABELS:
                if kind == "UPLOAD_JAR":
                    if not properties.get("ARTIFACT_NAME"):
                        project = properties.get("UPLOAD_SOURCE", "")
                        if partial and predecessors is None:
                            producer = _preceding_build(steps, index, project)
                            properties["ARTIFACT_NAME"] = (
                                steps[producer].get("properties", {}).get("ARTIFACT_NAME", "")
                                if producer is not None and (producer in selected or artifacts) else ""
                            )
                        else:
                            matches = [
                                name for name, (path, producer) in groups.items()
                                if (not project or path == project)
                                and (predecessors is None or producer in ancestors[index])
                            ]
                            properties["ARTIFACT_NAME"] = matches[-1] if matches else ""
                    group = groups.get(properties["ARTIFACT_NAME"])
                    if group is None or (predecessors is not None and group[1] not in ancestors[index]):
                        name = properties["ARTIFACT_NAME"]
                        existing = (artifacts or {}).get(name) if name not in selected_builds else None
                        if existing:
                            from .jar_artifact import select_jars
                            select_jars(existing, properties.get("JAR_FILTER", ""))
                        else:
                            message = "本次执行须包含对应的打包节点" if partial else "请先添加对应的打包步骤并选择产物组"
                            raise ValueError(tr(message))
                validate_upload(kind, properties)
            elif kind in EXECUTION_LABELS:
                validate(kind, properties)
            elif kind == "OPEN_SHELL":
                validate_shell_panel(properties)
            elif kind == "WAIT":
                wait_seconds(properties)
            elif kind == "HEALTH_CHECK":
                validate_health(properties)
            else:
                for key in STEP_FIELDS[kind]:
                    value = properties.get(key, "")
                    if not isinstance(value, str) or (key.endswith("PROJECT_PATH") and not value.strip()):
                        raise ValueError(tr("请填写有效的流程参数"))
                if properties.get("CONFLICT_POLICY", "rollback") not in POLICIES:
                    raise ValueError(tr("请填写有效的流程参数"))
            remote = kind in UPLOAD_LABELS or kind in {"HEALTH_CHECK", "OPEN_SHELL"} or kind.startswith("REMOTE_")
            if remote and servers is not None:
                name = properties.get("SERVER", "")
                if name not in servers:
                    raise ValueError(tr("服务器配置不存在：{0}", name))
                if name not in checked_servers:
                    from basic.shell.profile import ShellProfile
                    try:
                        ShellProfile(name, server_store.load(name)).validate()
                    except (OSError, ValueError) as error:
                        checked_servers[name] = str(error)
                    else:
                        checked_servers[name] = ""
                if checked_servers[name]:
                    raise ValueError(checked_servers[name])
        except (OSError, ValueError, TypeError, KeyError) as error:
            issues.append((index, str(error)))
    return steps, issues
