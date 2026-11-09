"""GUI-side process menus and one cancellable background operation."""

from dataclasses import dataclass, field
from threading import Event, Thread

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QMenu, QMessageBox

from common.i18n import tr
from .process_backend import restart_process, stop_process

from common.i18n.errors import error_message


@dataclass
class ProcessOperation:
    action: str
    context: object
    process: object
    cancel: Event = field(default_factory=Event)
    writer: object = None


class ProcessActions(QObject):
    _finished = Signal(object, str, str)

    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self._session = self._log_service = self._active = None
        self._closed = False
        self._finished.connect(self._complete, Qt.ConnectionType.QueuedConnection)

    @property
    def busy(self):
        return self._active is not None

    def bind_session(self, session, log_service=None):
        self._session, self._log_service = session, log_service
        session.disconnected.connect(self.cancel)
        if log_service is not None:
            log_service.register_producer(self.shutdown)

    def _current(self, context):
        now = self._session.connection_context() if self._session is not None and not self._closed else None
        return context is not None and now is not None and not context.connection_stop.is_set() and (
            context.transport is now.transport and context.connection_stop is now.connection_stop
        )

    def show_menu(self, position):
        item = self.panel.processes.itemAt(position)
        if item is None or self._closed:
            return
        process = item.data(0, Qt.ItemDataRole.UserRole)
        if process is None:
            return
        self.panel.processes.setCurrentItem(item)
        context = self._session.connection_context() if self._session is not None else None
        menu = QMenu(self.panel)
        stop = menu.addAction(tr("停止此服务"))
        restart = menu.addAction(tr("重启（不建议）"))
        enabled = self._current(context) and not self.busy and process.pid > 1 and bool(process.start_time)
        stop.setEnabled(enabled)
        restart.setEnabled(enabled)
        try:
            selected = menu.exec(self.panel.processes.viewport().mapToGlobal(position))
        finally:
            menu.deleteLater()
        if selected is stop:
            self._confirm("stop", context, process)
        elif selected is restart:
            self._confirm("restart", context, process)

    def _confirm(self, action, context, process):
        if not self._current(context) or self.busy:
            return
        restart = action == "restart"
        box = QMessageBox(self.panel.window())
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(tr("确认重启服务" if restart else "确认停止服务"))
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(tr("服务：{0}\nPID：{1}\n监听端口：{2}", process.name, process.pid, ", ".join(map(str, process.ports)) or "--"))
        box.setInformativeText(tr(
            "将停止原进程并尝试按原命令重启，服务会短暂中断。启动脚本、管道和输出重定向可能无法还原。建议使用原启动脚本或服务管理器。仍要继续吗？"
            if restart else "将发送正常终止信号，受管理的服务可能自动重启。确定继续吗？"
        ))
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        answer = box.exec()
        box.deleteLater()
        if answer != QMessageBox.StandardButton.Yes or not self._current(context) or self.busy:
            return
        job = ProcessOperation(action, context, process)
        if self._log_service is not None:
            try:
                job.writer = self._log_service.open_session("shell", process.name)
                job.writer.event("process_" + action, f"PID {process.pid}: {process.name}")
            except OSError:
                pass
        self._active = job
        self.panel.status.setText(tr("正在重启：{0}…" if restart else "正在停止：{0}…", process.name))
        Thread(target=self._work, args=(job,), name="monitor-process-action", daemon=True).start()

    def _work(self, job):
        try:
            operation = restart_process if job.action == "restart" else stop_process
            message, error = operation(job.context, job.cancel, job.process), ""
        except Exception as exc:
            message, error = "", error_message(exc) or type(exc).__name__
        if job.writer is not None:
            job.writer.event("failed" if error else "completed", error or message)
            job.writer.close()
        try:
            self._finished.emit(job, message, error)
        except RuntimeError:
            pass

    def _complete(self, job, message, error):
        if job is not self._active:
            return
        self._active = None
        if not self._current(job.context):
            return
        if error:
            text = tr("操作失败或结果未确认，未自动重试。请刷新服务状态后再操作。\n{0}", error)
            self.panel.status.setText(tr("操作失败"))
            QMessageBox.warning(self.panel.window(), tr("服务操作"), text)
        else:
            self.panel.status.setText(message)
            if job.action == "restart":
                QMessageBox.information(self.panel.window(), tr("服务操作"), message)
        self.panel.controller.refresh()

    def cancel(self, *_args):
        if self._active is not None:
            self._active.cancel.set()

    def shutdown(self, *_args):
        self._closed = True
        self.cancel()
        if self._log_service is not None:
            self._log_service.unregister_producer(self.shutdown)
