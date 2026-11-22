"""Application-owned workflow runs, independent of editor and panel lifetime."""
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from time import time

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QMessageBox
from common.i18n import tr
from common.i18n.errors import error_message
from common.i18n.widgets import QDialog
from basic.log.store import LogStore
from basic.log.writer import LogWriter
from .graph import WorkflowUpgradeRequired
from .history import RunHistoryStore, RunHistoryWriter
from .runner import TaskRunner
from .execution.connections import ExecutionServices
from .shell_panel import ShellPanelBridge


@dataclass
class WorkflowRun:
    runner: TaskRunner
    record: dict
    writer: LogWriter
    task_name: str
    number: int
    document: dict
    states: dict
    events: deque = field(default_factory=lambda: deque(maxlen=10000))
    artifacts: dict = field(default_factory=dict)
    conflict_dialog: object = None
    upload_progress: dict = field(default_factory=dict)

    @property
    def active(self):
        return self.record["finished"] is None


class TaskRunManager(QObject):
    changed = Signal(object)
    created = Signal(object)
    output_received = Signal(object, object, str)
    history_failed = Signal(str, str)

    def __init__(self, directory, registry, parent):
        super().__init__(parent)
        self.registry = registry
        self.runs = {}
        self._run_counts: dict[str, int] = {}
        self.store = RunHistoryStore(directory / "task_history")
        self.writer = RunHistoryWriter(self.store, self)
        self.writer.failed.connect(self.history_failed.emit)
        self.services = ExecutionServices(directory, self)
        self.services.log_service = registry.get_service("log")
        self.services.trust_requested.connect(self._confirm_host)
        self.bridge = ShellPanelBridge(registry, self)
        QApplication.instance().aboutToQuit.connect(self.writer.close)

    def _confirm_host(self, request):
        try:
            request["accepted"] = QMessageBox.question(
                self.parent(), tr("确认服务器主机密钥"),
                tr("服务器：{0}\n密钥类型：{1}\n指纹：{2}\n是否信任并保存？", request["host"], request["kind"], request["fingerprint"]),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            ) == QMessageBox.StandardButton.Yes
        finally:
            request["event"].set()

    def start(self, name, document, run_indexes, *, indexes=None, start_at=None,
              check_connections=True, scheduler=None, artifacts=None):
        if any(run.active for run in self.runs.values()) and self.registry.get_service("workflow_parallel") is None:
            raise WorkflowUpgradeRequired(tr("同时执行多个任务需要付费授权"))
        document = deepcopy(document)
        service = self.registry.get_service("log")
        if service:
            writer = service.open_session("task", name)
        else:
            log_store = LogStore(self.store.directory / "logs")
            writer = LogWriter.for_task(log_store, name)
        try:
            record = self.store.create(name, document["steps"], writer.path)
            record["flow"] = {
                "steps": [{key: deepcopy(step[key]) for key in ("type", "node_id", "position", "name") if key in step} for step in document["steps"]],
                "links": deepcopy(document.get("links", [])),
            }
            if "start_position" in document:
                record["flow"]["start_position"] = deepcopy(document["start_position"])
            record["selected_indexes"] = list(run_indexes)
            self.writer.submit(record)
        except Exception:
            writer.close()
            raise
        number = self._run_counts.get(name, 0) + 1
        self._run_counts[name] = number
        runner = TaskRunner(self, self.services)
        run = WorkflowRun(runner, record, writer, name, number, document,
                          dict.fromkeys(run_indexes, "waiting"))
        queued = Qt.ConnectionType.QueuedConnection
        runner.message.connect(lambda message: self._log(run, None, message), queued)
        runner.step_message.connect(lambda index, message: self._log(run, index, message), queued)
        def update_upload_progress(index, percent):
            run.upload_progress[index] = percent

        runner.upload_progress.connect(update_upload_progress, queued)
        runner.step_state.connect(lambda index, state: self._step_state(run, index, state), queued)
        runner.finished.connect(lambda success, message: self._finished(run, success, message), queued)
        runner.artifacts_ready.connect(lambda value: self._artifacts(run, value), queued)
        runner.conflict_requested.connect(lambda request: self._conflict(run, request), queued)
        runner.shell_requested.connect(self.bridge.open)
        self.runs[record["id"]] = run
        self.created.emit(run)
        try:
            runner.start(deepcopy(document), indexes=indexes, start_at=start_at, check_connections=check_connections,
                         scheduler=scheduler, artifacts=dict(artifacts or {}))
        except Exception as error:
            self._finished(run, False, tr("任务失败：{0}", error_message(error)))
        return run

    def _save(self, run):
        try:
            self.writer.submit(run.record)
        except (OSError, ValueError) as error:
            self.history_failed.emit(run.record["id"], str(error))

    def _log(self, run, index, message):
        text = str(message)
        run.events.append((index, text))
        run.writer.event("task" if index is None else f"task-step-{index}", text)
        self.output_received.emit(run, index, text)

    def _step_state(self, run, index, state):
        step = run.record["steps"][index]
        step["state"] = state
        if state == "running" and step["started"] is None:
            step["started"] = time()
        if state in {"success", "failed"}:
            step["finished"] = time()
        run.states[index] = state
        self._save(run)
        self.changed.emit(run)

    def _artifacts(self, run, artifacts):
        run.artifacts = artifacts
        self.changed.emit(run)

    def stop(self, run):
        if not run.active or run.runner.stop.is_set():
            return
        run.runner.stop.set()
        self._log(run, None, tr("正在停止，请等待执行结束"))
        if run.conflict_dialog is not None:
            run.conflict_dialog.reject()
        self.changed.emit(run)

    def _finished(self, run, success, message):
        stopped = not success and run.runner.stop.is_set()
        self._log(run, None, message)
        run.record.update(finished=time(), state="success" if success else "stopped" if stopped else "failed", message=str(message))
        for index in run.states:
            step = run.record["steps"][index]
            if stopped and step["state"] in {"failed", "running", "waiting"} and step["started"] is not None:
                step["state"] = "stopped"
                step["finished"] = step["finished"] or time()
            run.states[index] = step["state"]
        self._save(run)
        run.writer.close()
        run.runner.deleteLater()
        self.changed.emit(run)

    def _conflict(self, run, request):
        if run.runner.stop.is_set():
            request["event"].set()
            return
        from .git.conflict_dialog import ConflictDialog
        try:
            dialog = ConflictDialog(request, self.parent())
            run.conflict_dialog = dialog
            dialog.setWindowTitle(tr("解决冲突：{0}", run.task_name))
            def finished(result):
                request["answer"] = dict(dialog.resolutions) if result == QDialog.DialogCode.Accepted else None
                run.conflict_dialog = None
                request["event"].set()
                dialog.deleteLater()
                self.changed.emit(run)
            dialog.finished.connect(finished)
            dialog.show()
            self.changed.emit(run)
        except Exception as error:
            self._log(run, None, error_message(error))
            request["event"].set()
