"""Qt-thread task scheduling with independent, cancellable SFTP workers."""

import time
from collections import deque
from threading import Event, Thread

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication

from common.i18n import tr

from .backend import check_cancelled, list_directory, transfer
from .model import OverwriteRequest, TransferCancelled, TransferTask

from common.i18n.errors import error_message


class TransferController(QObject):
    connection_changed = Signal(bool)
    listing_ready = Signal(str, object)
    listing_failed = Signal(str, str)
    listing_started = Signal()
    listing_status = Signal(object)
    paid_transfer_requested = Signal()
    directory_invalidated = Signal(str)
    upload_completed = Signal(object)
    task_changed = Signal(object)
    tasks_cleared = Signal(object)
    overwrite_requested = Signal(object)
    _listed = Signal(int, str, object, str)
    _progress = Signal(str, object, object, str)
    _finished = Signal(str, str, object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._session = None
        self._registry = None
        self._context = None
        self._generation = 0
        self._listing = False
        self._pending_directory = None
        self._requested_directory = None
        self._browse_cancel = Event()
        self._tasks: dict[str, TransferTask] = {}
        self._pending = deque()
        self._active = None
        self._closed = False
        self._initial_snapshot = None
        self.listing_policy = None
        self.listing_handler = None
        self.partial_listing = False
        self._external_listing = False
        self._log_service = None
        self._writers = {}
        self.name = ""
        self.directory = "."
        self._listed.connect(self._apply_listing, Qt.ConnectionType.QueuedConnection)
        self._progress.connect(self._apply_progress, Qt.ConnectionType.QueuedConnection)
        self._finished.connect(self._apply_finished, Qt.ConnectionType.QueuedConnection)
        QApplication.instance().aboutToQuit.connect(self.shutdown)

    @property
    def is_listing(self) -> bool:
        return self._listing or self._external_listing or self._pending_directory is not None

    @property
    def registry(self):
        return self._registry

    def bind_registry(self, registry) -> None:
        self._registry = registry

    @property
    def requested_directory(self):
        return self._requested_directory

    def get_tasks(self):
        return tuple(self._tasks.values())

    def is_current_task(self, task) -> bool:
        return (
            not self._closed and self._context is not None and self._context is task.context
            and not task.context.connection_stop.is_set() and task.context.transport.is_active()
        )

    def bind_session(self, session, name: str, directory: str | None, log_service=None, initial_snapshot=None) -> None:
        if self._session is not None:
            self.disconnect_session()
        self._session = session
        self._initial_snapshot = initial_snapshot
        self.update_profile(name, directory)
        self._log_service = log_service
        if log_service is not None:
            log_service.register_producer(self.shutdown)
        session.connected.connect(self._connection_changed)
        session.disconnected.connect(self._connection_changed)
        self._connection_changed()

    def disconnect_session(self) -> None:
        session, self._session = self._session, None
        if session is not None:
            session.connected.disconnect(self._connection_changed)
            session.disconnected.disconnect(self._connection_changed)
        self._connection_changed()

    def update_profile(self, name: str, directory: str | None) -> None:
        self.name = name
        if not directory:
            self.directory = "."
            return
        directory = directory.strip().replace("\\", "/")
        # Match the existing SSH connector's handling of saved access paths.
        self.directory = directory if directory.startswith("/") or directory == "~" or directory.startswith("~/") else "/" + directory

    def _connection_changed(self, *_args) -> None:
        if self.listing_handler is not None:
            self.listing_handler.cancel()
        self._external_listing = self.partial_listing = False
        self._generation += 1
        self._browse_cancel.set()
        self._pending_directory = None
        self._requested_directory = None
        self.cancel_all()
        self._context = self._session.connection_context() if not self._closed and self._session is not None else None
        self.connection_changed.emit(self._context is not None)
        if self._context is not None:
            if self._initial_snapshot is not None:
                snapshot, self._initial_snapshot = self._initial_snapshot, None
                self.use_snapshot(snapshot)
            else:
                self.browse(self.directory)
        else:
            self._initial_snapshot = None
            self.listing_status.emit(tr("等待连接"))

    def use_snapshot(self, snapshot) -> None:
        if self._closed or self._context is None:
            return
        if self.listing_handler is not None and self.listing_handler.browse(snapshot.directory):
            return
        self.partial_listing = False
        self._generation += 1
        self._browse_cancel.set()
        self._pending_directory = None
        self.directory = snapshot.directory
        self._requested_directory = snapshot.directory
        self.listing_ready.emit(snapshot.directory, snapshot.entries)
        self.listing_status.emit(tr("共 {0} 项", len(snapshot.entries)))

    def browse(self, directory: str) -> None:
        if self._closed or self._context is None:
            return
        self._generation += 1
        self._browse_cancel.set()
        self._pending_directory = directory
        self._requested_directory = directory
        self._external_listing = self.partial_listing = False
        if self.listing_handler is not None and self.listing_handler.browse(directory):
            self._pending_directory = None
            return
        self._start_listing()

    def begin_page(self, directory: str) -> None:
        self._generation += 1
        self._browse_cancel.set()
        self._pending_directory = None
        self._requested_directory = directory
        self._external_listing = self.partial_listing = True
        self.listing_started.emit()
        self.listing_status.emit(tr("正在读取目录…"))

    def publish_page(self, directory: str, entries, *, notify: bool = True) -> None:
        if self._closed or self._context is None:
            return
        self._external_listing = False
        self.partial_listing = True
        self.directory = directory
        if notify:
            self.listing_ready.emit(directory, entries)

    def set_page_busy(self, busy: bool) -> None:
        self._external_listing = busy

    def page_failed(self, directory: str, error: str) -> None:
        self._external_listing = False
        if not self._closed:
            self.listing_failed.emit(directory, error)
            self.listing_status.emit(tr("读取目录失败：{0}", error))

    def cancel_listing(self) -> None:
        self._generation += 1
        self._browse_cancel.set()
        self._pending_directory = None
        self._external_listing = False
        if self.listing_handler is not None:
            self.listing_handler.cancel()

    def _start_listing(self) -> None:
        if self._listing or self._pending_directory is None or self._context is None or self._closed:
            return
        directory, self._pending_directory = self._pending_directory, None
        self._browse_cancel = Event()
        self._listing = True
        self.listing_started.emit()
        self.listing_status.emit(tr("正在读取目录…"))
        Thread(
            target=self._list_worker,
            args=(self._generation, self._context, self._browse_cancel, directory, self.listing_policy),
            name="sftp-directory", daemon=True,
        ).start()

    def _list_worker(self, generation, context, cancel, directory, listing_policy=None) -> None:
        try:
            path, entries = list_directory(context, cancel, directory, listing_policy=listing_policy)
            error = ""
        except Exception as exc:
            path, entries, error = directory, [], error_message(exc) or type(exc).__name__
        try:
            self._listed.emit(generation, path, entries, error)
        except RuntimeError:
            pass

    def _apply_listing(self, generation, directory, entries, error) -> None:
        self._listing = False
        if generation == self._generation and not self._closed:
            if error:
                self.listing_failed.emit(directory, error)
                self.listing_status.emit(tr("读取目录失败：{0}", error))
            else:
                self.directory = directory
                self.listing_ready.emit(directory, entries)
                self.listing_status.emit(tr("共 {0} 项", len(entries)))
        self._start_listing()

    def submit(self, direction: str, sources: list[str], destination: str, *, source_context=None) -> None:
        if self._context is None or self._closed or not sources:
            return
        handler = None
        if source_context is not None:
            same = source_context.transport is self._context.transport and source_context.connection_stop is self._context.connection_stop
            if direction == "upload" or not same:
                provider = self._registry.get_service("sftp_file_bridge") if self._registry is not None else None
                if provider is None:
                    self.paid_transfer_requested.emit()
                    return
                handler = provider.transfer_remote
        task = TransferTask(direction, tuple(dict.fromkeys(sources)), destination, self._context)
        task.source_context = source_context
        task.transfer_handler = handler
        self._tasks[task.id] = task
        self._pending.append(task.id)
        self.task_changed.emit(task)
        self._start_next()

    def _start_next(self) -> None:
        if self._active is not None or self._closed:
            return
        while self._pending:
            task = self._tasks[self._pending.popleft()]
            if task.state != "waiting":
                continue
            if task.transfer_handler is not None and (
                self._registry is None or self._registry.get_service("sftp_file_bridge") is None
            ):
                self.cancel(task.id)
                continue
            if task.context.connection_stop.is_set():
                self.cancel(task.id)
                continue
            resume = self._registry.get_service("sftp_resume") if self._registry is not None else None
            if resume is not None:
                resume.prepare(task)
            task.state = "running"
            self._active = task.id
            writer = None
            if self._log_service is not None:
                try:
                    writer = self._log_service.open_session("sftp", self.name)
                    writer.event(task.direction, f"{task.sources} -> {task.destination}")
                    self._writers[task.id] = writer
                except (OSError, ValueError) as exc:
                    task.detail = tr("日志写入失败：{0}", error_message(exc))
            self.task_changed.emit(task)
            Thread(target=self._transfer_worker, args=(task, writer), name="sftp-transfer", daemon=True).start()
            return

    def can_retry(self, identifier: str) -> bool:
        task = self._tasks.get(identifier)
        resume = self._registry.get_service("sftp_resume") if self._registry is not None else None
        return task is not None and resume is not None and resume.can_retry(task, self._context)

    def retry(self, identifier: str) -> None:
        if self.can_retry(identifier):
            task = self._tasks[identifier]
            self.submit(task.direction, list(task.sources), task.destination)

    def _transfer_worker(self, task, writer) -> None:
        last_update = 0.0
        last_position = None

        def check_connections():
            check_cancelled(task.context, task.cancel)
            if task.source_context is not None:
                check_cancelled(task.source_context, task.cancel)

        def progress(current, total, filename):
            nonlocal last_update, last_position
            now = time.monotonic()
            if (current == total and last_position != (current, total)) or now - last_update >= 0.1:
                last_update = now
                last_position = current, total
                self._progress.emit(task.id, current, total, filename)

        def confirm(path):
            request = OverwriteRequest(task, path)
            self.overwrite_requested.emit(request)
            deadline = time.monotonic() + 120
            try:
                while not request.completed.wait(0.1):
                    check_connections()
                    if time.monotonic() >= deadline:
                        raise TransferCancelled()
                check_connections()
                if request.answer == "cancel":
                    raise TransferCancelled()
                return request.answer == "overwrite"
            finally:
                request.completed.set()

        try:
            check_connections()
            skipped = transfer(task, progress, confirm)
            state = "completed"
            detail = tr("完成，跳过 {0} 项", skipped) if skipped else tr("传输完成")
        except Exception as exc:
            cancelled = isinstance(exc, TransferCancelled) or task.cancel.is_set() or task.context.connection_stop.is_set()
            state, detail = ("cancelled", tr("已取消")) if cancelled else ("failed", error_message(exc) or type(exc).__name__)
        if writer is not None:
            writer.event(state, str(detail))
            writer.close()
        try:
            self._finished.emit(task.id, state, detail)
        except RuntimeError:
            pass

    def _apply_progress(self, identifier, current, total, filename) -> None:
        task = self._tasks.get(identifier)
        if task is not None and task.state == "running":
            task.current, task.total, task.filename = current, total, filename
            self.task_changed.emit(task)

    def _apply_finished(self, identifier, state, detail) -> None:
        task = self._tasks[identifier]
        task.state, task.detail = state, detail
        self._writers.pop(identifier, None)
        self._active = None
        self.task_changed.emit(task)
        if task.direction == "upload" and self.is_current_task(task):
            # A failed or cancelled upload can already have published some
            # files. Consumers must invalidate every affected folder as well.
            self.directory_invalidated.emit(task.remote_directory or task.destination)
            self.browse(self._requested_directory or self.directory)
            if state == "completed":
                self.upload_completed.emit(task)
        self._start_next()

    def cancel(self, identifier: str) -> None:
        task = self._tasks.get(identifier)
        if task is None or task.state not in {"waiting", "running", "cancelling"}:
            return
        task.cancel.set()
        task.state = "cancelling" if identifier == self._active else "cancelled"
        self.task_changed.emit(task)

    def cancel_all(self) -> None:
        for identifier in self._tasks:
            self.cancel(identifier)

    def clear_finished(self) -> None:
        removed = tuple(identifier for identifier, task in self._tasks.items() if task.state not in {"waiting", "running", "cancelling"})
        self._tasks = {identifier: task for identifier, task in self._tasks.items() if task.state in {"waiting", "running", "cancelling"}}
        self._pending = deque(identifier for identifier in self._pending if identifier in self._tasks)
        self.tasks_cleared.emit(removed)

    def remove_finished(self, identifier: str) -> None:
        task = self._tasks.get(identifier)
        if task is None or task.state in {"waiting", "running", "cancelling"}:
            return
        self._tasks.pop(identifier)
        self._pending = deque(value for value in self._pending if value != identifier)
        self.tasks_cleared.emit((identifier,))

    def detach_log(self) -> None:
        if self._log_service is not None:
            self._log_service.unregister_producer(self.shutdown)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.listing_handler is not None:
            self.listing_handler.shutdown()
        self._context = None
        self._generation += 1
        self._browse_cancel.set()
        self.cancel_all()
        for writer in self._writers.values():
            writer.event("cancelled", tr("退出程序时停止传输"))
            writer.close()
