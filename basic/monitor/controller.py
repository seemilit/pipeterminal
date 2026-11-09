"""Visible-only background polling with cancellation and stale-result guards."""

from threading import Event, Thread

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from common.i18n import tr

from .collector import STATUS_COMMAND
from .model import parse_snapshot

from common.i18n.errors import error_message


class MonitorController(QObject):
    snapshot_ready = Signal(object)
    snapshot_reset = Signal()
    status_changed = Signal(object)
    _finished = Signal(int, object, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._session = None
        self._visible = False
        self._generation = 0
        self._running = False
        self._cancel = Event()
        self._timer = QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self.refresh)
        self._finished.connect(self._apply_result)
        QApplication.instance().aboutToQuit.connect(self.shutdown)

    def bind_session(self, session) -> None:
        self._session = session
        session.connected.connect(self._connection_changed)
        session.disconnected.connect(self._connection_changed)
        session.destroyed.connect(self.shutdown)
        self._connection_changed()

    @property
    def refresh_interval_seconds(self) -> int:
        return self._timer.interval() // 1000

    def set_visible(self, visible: bool) -> None:
        self._visible = visible
        if visible:
            if self._session is not None and self._session.state == "connected":
                self._timer.start()
            self.refresh()
        else:
            self._timer.stop()
            self._generation += 1
            self._cancel.set()

    def _connection_changed(self, *_args) -> None:
        self._generation += 1
        self._cancel.set()
        self.snapshot_reset.emit()
        self.status_changed.emit(tr("等待连接"))
        if self._visible and self._session is not None and self._session.state == "connected":
            self._timer.start()
            self.refresh()
        else:
            self._timer.stop()

    def refresh(self) -> None:
        if not self._visible or self._running or self._session is None:
            return
        if self._session.state != "connected":
            self.status_changed.emit(tr("等待连接"))
            return
        runner = self._session.command_runner()
        if runner is None:
            self.status_changed.emit(tr("监控连接不可用"))
            return
        self._cancel = Event()
        self._running = True
        self.status_changed.emit(tr("正在采集…"))
        Thread(
            target=self._collect, args=(self._generation, runner, self._cancel),
            name="server-monitor", daemon=True,
        ).start()

    def _collect(self, generation: int, runner, cancel: Event) -> None:
        try:
            snapshot, error = parse_snapshot(runner.run(STATUS_COMMAND, cancel)), ""
        except Exception as exc:
            snapshot, error = None, error_message(exc)
        try:
            self._finished.emit(generation, snapshot, error)
        except RuntimeError:
            pass

    def _apply_result(self, generation: int, snapshot, error: str) -> None:
        self._running = False
        if generation != self._generation or not self._visible:
            if self._visible:
                self.refresh()
            return
        if error:
            self.status_changed.emit(
                tr("监控仅支持 Linux 服务器") if "PT_MONITOR_UNSUPPORTED" in error
                else tr("采集失败：{0}", error)
            )
        else:
            self.snapshot_ready.emit(snapshot)

    def shutdown(self, *_args) -> None:
        self.set_visible(False)
        self._session = None
