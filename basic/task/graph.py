"""Persisted workflow connections and execution order."""

from collections import deque
from uuid import uuid4

from common.i18n import tr


START = "start"
PORTS = ("", "left", "right", "top", "bottom")
PARALLEL_REQUIRED = "免费版只支持一条流程线，并行分支需要付费授权"


class WorkflowUpgradeRequired(ValueError):
    pass


def ensure_graph(document):
    """Convert old sequential tasks on read, keeping deleted links deleted."""
    document["version"] = 3
    steps = document["steps"]
    if "links" in document:
        return
    links = document["links"] = []
    source, previous = START, {}
    for step in steps:
        target = step["node_id"] = uuid4().hex
        if not previous.get("connection_disabled", False):
            output = previous.get("output_port")
            incoming = step.get("input_port")
            links.append([source, target, output if output in PORTS else "", incoming if incoming in PORTS else ""])
        source, previous = target, step


def graph_structure(document):
    ids = [step.get("node_id") for step in document["steps"]]
    if any(not isinstance(node, str) or not node or node == START for node in ids) or len(set(ids)) != len(ids):
        raise ValueError(tr("任务文件格式无效"))
    outgoing = {node: [] for node in (START, *ids)}
    incoming = {node: [] for node in ids}
    links = document["links"]
    if not isinstance(links, list):
        raise ValueError(tr("任务文件格式无效"))
    for link in links:
        if not isinstance(link, list) or len(link) != 4 or not all(isinstance(value, str) for value in link):
            raise ValueError(tr("任务文件格式无效"))
        source, target, output, entry = link
        if source not in outgoing or target not in incoming or output not in PORTS or entry not in PORTS or target in outgoing[source]:
            raise ValueError(tr("任务文件格式无效"))
        outgoing[source].append(target)
        incoming[target].append(source)
    return ids, outgoing, incoming


def _reachable(outgoing, start):
    seen = set()
    pending = [start]
    while pending:
        node = pending.pop()
        if node not in seen:
            seen.add(node)
            pending.extend(outgoing[node])
    return seen


def validate_connection(document, source, target, parallel):
    _ids, outgoing, incoming = graph_structure(document)
    if source == target or source in _reachable(outgoing, target):
        raise ValueError(tr("连线不能形成循环"))
    if not parallel and (outgoing[source] or incoming[target]):
        raise WorkflowUpgradeRequired(tr(PARALLEL_REQUIRED))


def execution_plan(document, *, indexes=None, start_at=None, check_connections=True, parallel=False):
    ids, outgoing, incoming = graph_structure(document)
    selected = set(ids)
    if start_at is not None:
        selected = _reachable(outgoing, ids[start_at])
    elif indexes is not None:
        selected = {ids[index] for index in indexes}

    rank = {node: index for index, node in enumerate(ids)}
    if check_connections and start_at is None:
        reachable = _reachable(outgoing, START)
        missing = selected - reachable
        if missing:
            return (), {}, [(rank[node], str(tr("此节点未连接到开始"))) for node in sorted(missing, key=rank.get)]

    scope = selected if check_connections else set(ids)
    dependencies = {node: [parent for parent in incoming[node] if parent in scope] for node in scope}
    pending = {node: len(parents) for node, parents in dependencies.items()}
    ready = deque(node for node in ids if node in pending and not pending[node])
    order = []
    while ready:
        node = ready.popleft()
        order.append(rank[node])
        for child in outgoing[node]:
            if child in pending:
                pending[child] -= 1
                if pending[child] == 0:
                    ready.append(child)
    if len(order) != len(scope):
        return (), {}, [(-1, str(tr("连线不能形成循环")))]

    if check_connections and not parallel:
        # Start is a real source, even though it is not an executable step.
        sources = selected | ({START} if start_at is None else set())
        if any(sum(child in selected for child in outgoing[node]) > 1 for node in sources):
            raise WorkflowUpgradeRequired(tr(PARALLEL_REQUIRED))
    predecessors = {
        rank[node]: tuple(rank[parent] for parent in parents if parent in selected)
        for node, parents in dependencies.items() if node in selected
    }
    return tuple(index for index in order if ids[index] in selected), predecessors, []


def append_node(document, step, source, output="", entry=""):
    step["node_id"] = uuid4().hex
    document["steps"].append(step)
    if source is not None:
        document["links"].append([source, step["node_id"], output, entry])


def remove_node(document, index):
    node = document["steps"].pop(index)["node_id"]
    links = document["links"]
    incoming = [link for link in links if link[1] == node]
    outgoing = [link for link in links if link[0] == node]
    links[:] = [link for link in links if node not in link[:2]]
    if len(incoming) == 1 and len(outgoing) == 1:
        source, target = incoming[0][0], outgoing[0][1]
        if not any(link[:2] == [source, target] for link in links):
            links.append([source, target, incoming[0][2], outgoing[0][3]])
