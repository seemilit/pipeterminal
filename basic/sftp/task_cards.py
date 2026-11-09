"""Original-style compact transfer cards, observing the existing task queue."""

import posixpath
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QHBoxLayout, QMenu, QScrollArea, QSizePolicy, QStyle, QVBoxLayout, QWidget

from common.i18n import tr
from common.licensing.prompt import prompt_activation
from common.i18n.widgets import QLabel, QProgressBar, QPushButton

from .model import format_size
from .task_list import STATE_LABELS


class TransferTaskCards(QWidget):
    count_changed = Signal(int)
    remote_location_requested = Signal(object)

    def __init__(self, controller, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._rows = {}
        self._closed = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rows = QWidget()
        self.rows_layout = QVBoxLayout(rows)
        self.rows_layout.setContentsMargins(6, 0, 6, 6)
        self.rows_layout.setSpacing(2)
        self.empty = QLabel(tr("暂无传输任务"))
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setMinimumHeight(180)
        self.empty.setEnabled(False)
        self.rows_layout.addWidget(self.empty)
        self.rows_layout.addStretch(1)
        self.scroll_area.setWidget(rows)
        layout.addWidget(self.scroll_area)
        controller.task_changed.connect(self._display_task)
        controller.tasks_cleared.connect(self._tasks_cleared)
        for task in controller.get_tasks():
            self._display_task(task)

    @property
    def count(self) -> int:
        return len(self._rows)

    def _create_row(self, task):
        row = QFrame()
        row.setObjectName("transferTaskCard")
        row.setFixedHeight(78)
        layout = QVBoxLayout(row)
        layout.setContentsMargins(4, 6, 4, 7)
        layout.setSpacing(4)
        heading = QHBoxLayout()
        heading.setSpacing(4)
        name = QLabel()
        name.setTextFormat(Qt.TextFormat.PlainText)
        name.setMinimumWidth(0)
        name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        heading.addWidget(name, 1)
        folder = QPushButton()
        folder.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        folder.setFixedSize(24, 22)
        folder.setToolTip(tr("打开所在文件夹") + "\n" + task.destination)
        folder.setVisible(task.direction == "download")
        folder.clicked.connect(lambda _checked=False, value=task.id: self._open_folder(value))
        heading.addWidget(folder)
        remove = QPushButton("×")
        remove.setFixedSize(24, 22)
        remove.clicked.connect(lambda _checked=False, value=task.id: self._operate_task(value))
        heading.addWidget(remove)
        layout.addLayout(heading)
        progress = QProgressBar()
        progress.setFixedHeight(16)
        layout.addWidget(progress)
        status = QLabel()
        status.setTextFormat(Qt.TextFormat.PlainText)
        status.setMinimumWidth(0)
        status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(status)
        for widget in (row, name, progress, status):
            widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            widget.customContextMenuRequested.connect(
                lambda position, source=widget, value=task.id: self._show_context_menu(value, source, position)
            )
        self.rows_layout.insertWidget(self.rows_layout.count() - 1, row)
        self._rows[task.id] = row, name, progress, status, remove, folder, task
        self.empty.hide()
        self.count_changed.emit(self.count)
        return self._rows[task.id]

    def _display_task(self, task) -> None:
        if self._closed:
            return
        row, name, progress, status, remove, folder, _task = self._rows.get(task.id) or self._create_row(task)
        title = task.filename or ", ".join(
            Path(source).name if task.direction == "upload" else posixpath.basename(source.rstrip("/"))
            for source in task.sources
        )
        name.setText(tr("上传：{0}" if task.direction == "upload" else "下载：{0}", title))
        name.setToolTip("\n".join(task.sources))
        summary = tr(STATE_LABELS[task.state]) + "  " + tr("已处理：{0} / {1}", format_size(task.current), format_size(task.total))
        status.setText(summary)
        status.setToolTip(task.detail or task.destination)
        if task.state == "running" and task.total == 0:
            progress.setRange(0, 0)
        else:
            progress.setRange(0, 1000)
            progress.setValue(1000 if task.state == "completed" else min(1000, int(task.current * 1000 / task.total)) if task.total else 0)
        progress.setToolTip(summary)
        active = task.state in {"waiting", "running", "cancelling"}
        remove.setToolTip(tr("取消传输" if active else "移除记录"))
        remove.setEnabled(task.state != "cancelling")
        folder.setEnabled(task.direction == "download" and task.state == "completed")

    def _operate_task(self, identifier: str) -> None:
        cached = self._rows.get(identifier)
        if cached is None:
            return
        if cached[-1].state in {"waiting", "running"}:
            self.controller.cancel(identifier)
        elif cached[-1].state not in {"waiting", "running", "cancelling"}:
            self.controller.remove_finished(identifier)

    def _open_folder(self, identifier: str) -> None:
        cached = self._rows.get(identifier)
        if cached is not None and cached[-1].direction == "download":
            directory = Path(cached[-1].destination)
            if directory.is_dir():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory.resolve())))

    def _locate_remote(self, identifier: str) -> None:
        cached = self._rows.get(identifier)
        if cached is not None and cached[-1].direction == "upload" and self.controller.is_current_task(cached[-1]):
            self.remote_location_requested.emit(cached[-1])

    def _show_context_menu(self, identifier: str, source, position) -> None:
        cached = self._rows.get(identifier)
        if self._closed or cached is None:
            return
        task = cached[-1]
        menu = QMenu(self)
        if task.direction == "download":
            location = menu.addAction(tr("打开所在文件夹"))
            location.setEnabled(Path(task.destination).is_dir())
            location.triggered.connect(lambda _checked=False: self._open_folder(identifier))
        else:
            location = menu.addAction(tr("定位到服务器目录"))
            location.setEnabled(self.controller.is_current_task(task))
            location.triggered.connect(lambda _checked=False: self._locate_remote(identifier))
        menu.addSeparator()
        if self.controller.can_retry(identifier):
            retry = menu.addAction(tr("继续传输"))
            retry.triggered.connect(lambda _checked=False: self.controller.retry(identifier))
        elif (task.state in {"failed", "cancelled"} and self.controller.is_current_task(task)
              and self.controller.registry is not None and self.controller.registry.get_service("sftp_resume") is None):
            retry = menu.addAction(tr("继续传输"))
            retry.triggered.connect(lambda: prompt_activation(self.controller.registry, self, tr("断点续传")))
        active = task.state in {"waiting", "running", "cancelling"}
        operation = menu.addAction(tr("取消传输" if active else "移除记录"))
        operation.setEnabled(task.state != "cancelling")
        operation.triggered.connect(lambda _checked=False: self._operate_task(identifier))
        try:
            menu.exec(source.mapToGlobal(position))
        finally:
            menu.deleteLater()

    def _tasks_cleared(self, identifiers) -> None:
        if self._closed:
            return
        for identifier in identifiers:
            cached = self._rows.pop(identifier, None)
            if cached is not None:
                self.rows_layout.removeWidget(cached[0])
                cached[0].deleteLater()
        self.empty.setVisible(not self._rows)
        self.count_changed.emit(self.count)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.controller.task_changed.disconnect(self._display_task)
        self.controller.tasks_cleared.disconnect(self._tasks_cleared)
