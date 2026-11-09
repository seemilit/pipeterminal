"""Transfer records shared by workspace tabs and the standalone task window."""

import posixpath
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from common.i18n import tr
from common.i18n.widgets import QProgressBar, QPushButton, QTreeWidget, QTreeWidgetItem

from .model import format_size


STATE_LABELS = {
    "waiting": "等待传输", "running": "正在传输", "cancelling": "正在取消…",
    "completed": "已完成", "failed": "传输失败", "cancelled": "已取消",
}


class TransferTaskList(QWidget):
    def __init__(self, controller, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._task_rows = {}
        self._closed = False
        layout = QVBoxLayout(self)
        self.tasks = QTreeWidget()
        self.tasks.setColumnCount(5)
        self.tasks.setHeaderLabels([tr("方向"), tr("文件"), tr("进度"), tr("状态"), tr("详情")])
        self.tasks.setRootIsDecorated(False)
        self.tasks.setAlternatingRowColors(True)
        for column, width in enumerate((70, 190, 180, 100, 390)):
            self.tasks.setColumnWidth(column, width)
        self.tasks.itemSelectionChanged.connect(self._update_cancel_button)
        layout.addWidget(self.tasks, 1)
        actions = QHBoxLayout()
        self.cancel_selected = QPushButton(tr("取消选中任务"))
        self.cancel_selected.clicked.connect(self._cancel_selected)
        cancel_all = QPushButton(tr("取消全部任务"))
        cancel_all.clicked.connect(lambda: self.controller.cancel_all())
        clear = QPushButton(tr("清除已结束任务"))
        clear.clicked.connect(self.controller.clear_finished)
        actions.addStretch(1)
        actions.addWidget(self.cancel_selected)
        actions.addWidget(cancel_all)
        actions.addWidget(clear)
        layout.addLayout(actions)
        controller.task_changed.connect(self._display_task)
        controller.tasks_cleared.connect(self._tasks_cleared)
        for task in controller.get_tasks():
            self._display_task(task)
        self._update_cancel_button()

    def _display_task(self, task) -> None:
        if self._closed:
            return
        cached = self._task_rows.get(task.id)
        if cached is None:
            item = QTreeWidgetItem()
            item.setData(0, Qt.ItemDataRole.UserRole, task.id)
            self.tasks.addTopLevelItem(item)
            progress = QProgressBar()
            progress.setFixedHeight(22)
            self.tasks.setItemWidget(item, 2, progress)
            self._task_rows[task.id] = item, progress, task
        else:
            item, progress, _previous = cached
        title = task.filename or ", ".join(
            Path(source).name if task.direction == "upload" else posixpath.basename(source)
            for source in task.sources
        )
        item.setText(0, tr("上传") if task.direction == "upload" else tr("下载"))
        item.setText(1, title)
        item.setText(3, tr(STATE_LABELS[task.state]))
        item.setText(4, task.detail or task.destination)
        item.setToolTip(1, "\n".join(task.sources))
        item.setToolTip(4, str(task.detail or task.destination))
        if task.state == "running" and task.total == 0:
            progress.setRange(0, 0)
        else:
            progress.setRange(0, 1000)
            progress.setValue(1000 if task.state == "completed" else min(1000, int(task.current * 1000 / task.total)) if task.total else 0)
        progress.setToolTip(tr("已处理：{0} / {1}", format_size(task.current), format_size(task.total)))
        self._update_cancel_button()

    def _update_cancel_button(self) -> None:
        selected = self.tasks.currentItem()
        cached = self._task_rows.get(selected.data(0, Qt.ItemDataRole.UserRole)) if selected else None
        self.cancel_selected.setEnabled(cached is not None and cached[2].state in {"waiting", "running"})

    def _cancel_selected(self) -> None:
        selected = self.tasks.currentItem()
        if selected is not None:
            self.controller.cancel(selected.data(0, Qt.ItemDataRole.UserRole))

    def _tasks_cleared(self, identifiers) -> None:
        if self._closed:
            return
        for identifier in identifiers:
            cached = self._task_rows.pop(identifier, None)
            if cached is not None:
                item = cached[0]
                self.tasks.takeTopLevelItem(self.tasks.indexOfTopLevelItem(item))
        self._update_cancel_button()

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.controller.task_changed.disconnect(self._display_task)
        self.controller.tasks_cleared.disconnect(self._tasks_cleared)
