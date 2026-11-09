"""Read-only log viewer with asynchronous snapshots and guarded deletion."""

import re
from threading import Thread

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QVBoxLayout

from common.i18n import tr
from common.i18n.widgets import QLabel, QPushButton
from common.qt.module_page import ModulePage

from common.i18n.errors import error_message

from .viewer import LogViewer


_TIMESTAMP_PREFIX = re.compile(r"^\[[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}\] ?", re.MULTILINE)


class LogPage(ModulePage):
    _loaded = Signal(int, str, bool, str)

    def __init__(self, pinned_id: str | None = None) -> None:
        super().__init__()
        self.service = None
        self._items: list[tuple[str, str]] = []
        self._pinned_id = pinned_id
        self._selected: str | None = pinned_id
        self._request = 0
        self._reading = False
        self._raw_text = ""
        self._show_timestamps = True
        self.file_actions = {"delete": self.delete_log}
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.title = QLabel()
        if pinned_id is not None:
            self.title.setText(pinned_id)
        header.addWidget(self.title, 1)
        self.time_button = QPushButton(tr("隐藏时间"))
        self.time_button.clicked.connect(self._toggle_timestamps)
        header.addWidget(self.time_button)
        refresh = QPushButton(tr("刷新"))
        refresh.clicked.connect(self._poll)
        header.addWidget(refresh)
        self.log_viewer = LogViewer(self, header)
        layout.addLayout(header)
        self.viewer = self.log_viewer.text
        self.viewer.setFont(QFont("Cascadia Mono", 10))
        layout.addWidget(self.log_viewer, 1)
        self.notice = QLabel()
        layout.addWidget(self.notice)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._poll)
        self._loaded.connect(self._display_snapshot)

    def bind_registry(self, registry) -> None:
        super().bind_registry(registry)
        self.service = registry.get_service("log")

    def bind_service(self, service) -> None:
        self.service = service

    def activate(self) -> None:
        self._poll()
        self._timer.start()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def directory_items(self) -> list[tuple[str, str]]:
        return self._items

    def current_item_id(self) -> str | None:
        return self._selected

    def select_item(self, item_id: str) -> bool:
        if item_id != self._selected:
            self._selected = item_id
            self._request += 1
            self._raw_text = ""
            self.viewer.clear()
            self.title.setText(item_id)
            self._read_snapshot()
            self.actions_changed.emit()
        return True

    def is_action_enabled(self, action_id: str) -> bool:
        return (
            action_id == "delete" and self._selected is not None and self.service is not None
            and self._pinned_id is None
            and not self.service.is_active(self._selected)
        )

    def _poll(self) -> None:
        if self.service is None:
            return
        if self._pinned_id is not None:
            self._read_snapshot()
            return
        try:
            items = self.service.store.list_logs()
            if items != self._items:
                self._items = items
                available = {identifier for identifier, _name in items}
                if self._selected not in available:
                    self._selected = None
                    self._request += 1
                    self._raw_text = ""
                    self.viewer.clear()
                    self.title.clear()
                    if items:
                        self.select_item(items[0][0])
                self.directory_changed.emit()
            self.actions_changed.emit()
            self._read_snapshot()
        except (OSError, ValueError) as exc:
            self.notice.setText(error_message(exc))

    def _read_snapshot(self) -> None:
        if self._reading or self._selected is None or self.service is None:
            return
        self._reading = True
        request, identifier = self._request, self._selected
        Thread(target=self._read_worker, args=(request, identifier), name="log-reader", daemon=True).start()

    def _read_worker(self, request: int, identifier: str) -> None:
        try:
            text, truncated = self.service.store.read(identifier)
            error = ""
        except (OSError, ValueError) as exc:
            text, truncated, error = "", False, error_message(exc)
        try:
            self._loaded.emit(request, text, truncated, error)
        except RuntimeError:
            pass

    def _display_snapshot(self, request: int, text: str, truncated: bool, error: str) -> None:
        self._reading = False
        if request != self._request:
            self._read_snapshot()
            return
        if error:
            self.notice.setText(error)
            return
        self.notice.setText(tr("仅预览最后 4 MB，日志文件完整保留") if truncated else "")
        if text != self._raw_text:
            self._raw_text = text
            self._render_snapshot()

    def _toggle_timestamps(self) -> None:
        self._show_timestamps = not self._show_timestamps
        self.time_button.setText(tr("隐藏时间" if self._show_timestamps else "显示时间"))
        self._render_snapshot()

    def _render_snapshot(self) -> None:
        text = self._raw_text if self._show_timestamps else _TIMESTAMP_PREFIX.sub("", self._raw_text)
        if text != self.viewer.toPlainText():
            bar = self.viewer.verticalScrollBar()
            following = bar.value() == bar.maximum() and not self.log_viewer.has_match
            position = bar.value()
            self.viewer.setPlainText(text)
            if following:
                self.viewer.moveCursor(QTextCursor.MoveOperation.End)
            else:
                bar.setValue(position)

    def delete_log(self) -> None:
        if not self.is_action_enabled("delete"):
            return
        if QMessageBox.question(
            self, tr("删除"), tr("确定删除日志“{0}”吗？", self._selected),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.service.store.delete(self._selected)
            self._selected = None
            self._request += 1
            self._poll()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, tr("日志"), error_message(exc))
