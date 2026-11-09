"""Lazy log writers and shutdown flushing for all registered producers."""

import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from .store import LogStore
from .writer import LogWriter


class LogService(QObject):
    write_failed = Signal(object, str)

    def __init__(self, store: LogStore) -> None:
        super().__init__(QApplication.instance())
        self.store = store
        self._writers: list[LogWriter] = []
        self._producers: list[Callable[[], None]] = []
        self._daily_writers: dict[tuple[str, str], LogWriter] = {}
        self._viewers: dict[str, object] = {}
        QApplication.instance().aboutToQuit.connect(self.shutdown)

    def register_producer(self, stop: Callable[[], None]) -> None:
        if stop not in self._producers:
            self._producers.append(stop)

    def unregister_producer(self, stop: Callable[[], None]) -> None:
        if stop in self._producers:
            self._producers.remove(stop)

    def open_session(self, category: str, name: str) -> LogWriter:
        self._writers = [writer for writer in self._writers if not writer.closed.is_set()]
        writer = LogWriter(self.store.new_path(category, name), error_callback=self.write_failed.emit)
        self._writers.append(writer)
        return writer

    def is_active(self, identifier: str) -> bool:
        path = self.store.path_for(identifier)
        return any(writer.path == path and not writer.closed.is_set() for writer in self._writers)

    def record_event(self, category: str, kind: str, message: str) -> LogWriter:
        key = category, datetime.now().strftime("%Y%m%d")
        for previous in list(self._daily_writers):
            if previous[0] == category and previous != key:
                self._daily_writers.pop(previous).close()
        writer = self._daily_writers.get(key)
        if writer is None or writer.closed.is_set():
            writer = self.open_session(category, "operations")
            self._daily_writers[key] = writer
        writer.event(kind, message)
        return writer

    def open_viewer(self, path: Path, parent=None) -> None:
        """GUI-thread entry point for one pinned, automatically refreshed log."""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QDialogButtonBox, QVBoxLayout
        from common.i18n import tr
        from common.i18n.widgets import QDialog
        from .page import LogPage

        identifier = path.resolve().relative_to(self.store.directory).as_posix()
        self.store.path_for(identifier)
        dialog = self._viewers.get(identifier)
        if dialog is None:
            dialog = QDialog(parent)
            dialog.setWindowTitle(tr("会话日志：{0}", path.stem))
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            dialog.resize(760, 460)
            layout = QVBoxLayout(dialog)
            viewer = LogPage(identifier)
            viewer.bind_service(self)
            layout.addWidget(viewer, 1)
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.rejected.connect(dialog.close)
            layout.addWidget(buttons)
            dialog.finished.connect(lambda _result: viewer._timer.stop())
            dialog.destroyed.connect(lambda: self._viewers.pop(identifier, None))
            self._viewers[identifier] = dialog
            dialog.show()
            viewer.activate()
        else:
            dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def shutdown(self) -> None:
        for stop in list(self._producers):
            stop()
        for writer in self._writers:
            writer.close()
        deadline = time.monotonic() + 3
        for writer in self._writers:
            writer.wait(max(0, deadline - time.monotonic()))
