"""Background execution of independent workflow actions."""

from threading import Event, Lock, Thread
from time import monotonic

from PySide6.QtCore import QObject, Signal

from common.i18n import tr
from common.i18n.errors import error_message

from .git.merge import GitMergePush
from .git.operations import GitWorkflow
from .git.build import MavenBuild
from .jar_artifact import detect_jars
from .schema import STEP_LABELS
from .execution.schema import STEP_LABELS as EXECUTION_LABELS
from .execution.engine import ExecutionEngine
from .validation import prepare_workflow
from .graph import ensure_graph, execution_plan
from .health import execute_health
from .wait import execute_wait
from .upload import STEP_LABELS as UPLOAD_LABELS, UploadEngine


class TaskRunner(QObject):
    message = Signal(object)
    finished = Signal(bool, object)
    step_state = Signal(int, str)
    conflict_requested = Signal(object)
    artifacts_ready = Signal(object)
    shell_requested = Signal(object)

    def __init__(self, parent=None, services=None):
        super().__init__(parent)
        self.services = services
        self.stop = Event()
        self._conflict_lock = Lock()

    def start(self, document, *, indexes=None, start_at=None, check_connections=True, scheduler=None, artifacts=None):
        self.stop.clear()
        available = {name: tuple(paths) for name, paths in (artifacts or {}).items()} if indexes is not None or start_at is not None else {}
        Thread(
            target=self._run, args=(document, indexes, start_at, check_connections, scheduler, available),
            name="task-workflow", daemon=True,
        ).start()

    def _run(self, document, indexes=None, start_at=None, check_connections=True, scheduler=None, artifacts=None):
        artifacts = dict(artifacts or {})
        try:
            ensure_graph(document)
            order, predecessors, issues = execution_plan(
                document, indexes=indexes, start_at=start_at,
                check_connections=check_connections, parallel=scheduler is not None,
            )
            for index in order:
                step = document["steps"][index]
                if step["type"] == "MAVEN_BUILD":
                    name = step.get("properties", {}).get("ARTIFACT_NAME", "artifact")
                    if isinstance(name, str):
                        artifacts.pop(name.strip(), None)
            self.artifacts_ready.emit(dict(artifacts))
            steps = []
            if not issues:
                steps, issues = prepare_workflow(
                    document, self.services.store if self.services else None,
                    indexes=order, check_connections=False,
                    predecessors=predecessors if check_connections else None,
                    allow_existing_jars=indexes is not None or start_at is not None,
                )
            if issues:
                raise ValueError("\n".join(str(tr("第 {0} 步：{1}", index + 1, message)) if index >= 0 else message for index, message in issues))
            artifacts_lock = Lock()

            def execute(index):
                self._execute_step(index, steps[index], artifacts, artifacts_lock, scheduler is not None)

            if scheduler is not None and check_connections:
                scheduler.run(order, predecessors, steps, execute, self.stop, self.services)
            else:
                for index in order:
                    execute(index)
            if self.stop.is_set():
                raise RuntimeError(tr("执行已停止"))
        except Exception as exc:
            self.finished.emit(False, tr("任务失败：{0}", error_message(exc)))
        else:
            self.finished.emit(True, tr("任务执行完成"))

    def _execute_step(self, index, step, artifacts, artifacts_lock, parallel):
        if self.stop.is_set():
            raise RuntimeError(tr("执行已停止"))
        self.step_state.emit(index, "running")
        kind, properties = step["type"], step["properties"]
        self.message.emit(tr("执行第 {0} 步：{1}", index + 1, tr(STEP_LABELS[kind])))

        def log(message):
            self.message.emit(tr("第 {0} 步：{1}", index + 1, message) if parallel else message)

        def resolve(request):
            return self._resolve(index, request)

        try:
            if kind in EXECUTION_LABELS:
                ExecutionEngine(self.services, log, self.stop).execute(kind, properties)
            elif kind in UPLOAD_LABELS:
                with artifacts_lock:
                    available = dict(artifacts)
                if kind == "UPLOAD_JAR" and "local_jar_build" in step:
                    project, filters = step["local_jar_build"]
                    available[properties["ARTIFACT_NAME"]] = detect_jars(project.resolve(), self.stop, filters)
                UploadEngine(self.services, log, self.stop).execute(kind, properties, artifacts=available)
            elif kind == "MAVEN_BUILD":
                name = properties["ARTIFACT_NAME"].strip()
                built = MavenBuild(self.services, log, self.stop).execute(properties)
                with artifacts_lock:
                    artifacts[name] = built
                    self.artifacts_ready.emit(dict(artifacts))
            elif kind == "OPEN_SHELL":
                self._open_shell(properties, log)
            elif kind == "HEALTH_CHECK":
                execute_health(properties, self.services, log, self.stop)
            elif kind == "WAIT":
                execute_wait(properties, log, self.stop)
            elif kind == "MERGE_BRANCH":
                GitMergePush(log, resolve).execute(properties)
            else:
                GitWorkflow(log, resolve).execute_action(kind, properties)
        except Exception:
            self.step_state.emit(index, "failed")
            raise
        self.step_state.emit(index, "success")

    def _open_shell(self, properties, log):
        request = {"properties": dict(properties), "event": Event(), "cancel": Event(), "error": ""}
        self.shell_requested.emit(request)
        deadline = monotonic() + 150
        while not request["event"].wait(0.1):
            if self.stop.is_set() or monotonic() >= deadline:
                request["cancel"].set()
                raise RuntimeError(tr("执行已停止") if self.stop.is_set() else tr("打开 Shell 面板超时"))
        if self.stop.is_set():
            request["cancel"].set()
            raise RuntimeError(tr("执行已停止"))
        if request["error"]:
            raise RuntimeError(request["error"])
        log(tr("Shell 面板已打开：{0}", properties["SERVER"]))

    def _resolve(self, index, request):
        with self._conflict_lock:
            if self.stop.is_set():
                return None
            request["event"] = Event()
            request["answer"] = None
            self.step_state.emit(index, "waiting")
            self.message.emit(tr("流程已暂停，等待解决冲突"))
            self.conflict_requested.emit(request)
            request["event"].wait()
            self.step_state.emit(index, "running")
            return request["answer"]
