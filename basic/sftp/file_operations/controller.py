"""One file-operation worker; all notifications return to the Qt thread."""

from dataclasses import dataclass, field
from threading import Event, Thread
from uuid import uuid4

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication

from common.i18n import tr
from ..model import TransferCancelled

from common.i18n.errors import error_message


@dataclass
class FileOperation:
    label: str
    context: object
    owner: str
    affected: tuple[str, ...]
    id: str = field(default_factory=lambda: uuid4().hex)
    cancel: Event = field(default_factory=Event)
    result: dict = field(default_factory=dict)
    writer: object = None


class FileOperationController(QObject):
    completed = Signal(object, str)
    directories_changed = Signal(object)
    busy_changed = Signal(bool)
    progress_changed = Signal(str, int, int, str)
    _finished = Signal(object, str)
    _progress = Signal(str, int, int, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._session = self._log_service = self._active = None
        self._closed = False
        self._name = ""
        self._finished.connect(self._apply_result, Qt.ConnectionType.QueuedConnection)
        self._progress.connect(self._apply_progress, Qt.ConnectionType.QueuedConnection)
        QApplication.instance().aboutToQuit.connect(self.shutdown)

    @property
    def busy(self) -> bool:
        return self._active is not None

    @property
    def log_service(self):
        return self._log_service

    def bind_session(self, session, name="", log_service=None) -> None:
        if self._session is session:
            return
        self._session, self._name, self._log_service = session, name, log_service
        session.disconnected.connect(self.cancel)
        if log_service is not None:
            log_service.register_producer(self.shutdown)

    def current(self, context) -> bool:
        if self._closed or context is None:
            return False
        now = self._session.connection_context() if self._session is not None else None
        return not self._closed and now is not None and (
            now.transport is context.transport and now.connection_stop is context.connection_stop
            and not context.connection_stop.is_set()
        )

    def start(self, label, context, work, *, owner="", affected=(), paths=()):
        if self.busy or not self.current(context):
            return None
        job = FileOperation(label, context, owner, tuple(affected))
        if self._log_service is not None:
            try:
                job.writer = self._log_service.open_session("sftp", self._name)
                job.writer.event("file_operation", f"{label}: {paths}")
            except OSError:
                pass
        self._active = job
        self.busy_changed.emit(True)
        Thread(target=self._work, args=(job, work), name="sftp-file-operation", daemon=True).start()
        return job

    def _work(self, job, work) -> None:
        def progress(current, total, name):
            self._progress.emit(job.id, current, total, name)

        try:
            work(job.context, job.cancel, job.result, progress)
            error = ""
        except (TransferCancelled, ConnectionAbortedError):
            error = str(tr("操作已取消"))
        except Exception as exc:
            error = str(tr("操作已取消")) if job.cancel.is_set() else error_message(exc) or type(exc).__name__
        if job.writer is not None:
            job.writer.event("failed" if error else "completed", error or str(tr("操作完成")))
            if job.result.get("leftovers"):
                job.writer.event("leftovers", "\n".join(job.result["leftovers"]))
            job.writer.close()
        try:
            self._finished.emit(job, error)
        except RuntimeError:
            pass

    def _apply_progress(self, identifier, current, total, name) -> None:
        if self._active is not None and self._active.id == identifier and not self._closed:
            self.progress_changed.emit(identifier, current, total, name)

    def _apply_result(self, job, error) -> None:
        if self._active is not job:
            return
        self._active = None
        if self._closed:
            return
        if job.cancel.is_set() and not error and not job.affected and not job.result.get("affected"):
            error = str(tr("操作已取消"))
        if self.current(job.context):
            affected = tuple(dict.fromkeys((*job.affected, *job.result.get("affected", ()))))
            if affected:
                self.directories_changed.emit(affected)
        else:
            error = str(tr("连接已改变，操作结果已丢弃"))
        self.busy_changed.emit(False)
        self.completed.emit(job, error)

    def cancel(self, *_args) -> None:
        if self._active is not None:
            self._active.cancel.set()

    def shutdown(self) -> None:
        self._closed = True
        self.cancel()
        if self._log_service is not None:
            self._log_service.unregister_producer(self.shutdown)
