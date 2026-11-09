"""Conflict file chooser; repository operations remain on the workflow worker."""

from pathlib import PurePosixPath
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QMenu, QMessageBox, QStyle, QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator, QVBoxLayout
from common.i18n import tr
from common.i18n.widgets import QDialog, QLabel, QPushButton
from .conflict_session import ConflictSession


class ConflictDialog(QDialog):
    def __init__(self, request, parent=None):
        super().__init__(parent)
        self.request = request
        self.session = ConflictSession(request)
        self._editors = {}
        self._rows = {}
        self._finished = False
        self.setWindowTitle(tr("解决冲突"))
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint | Qt.WindowType.WindowMinimizeButtonHint)
        self.resize(1120, 700)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("正在将【{0}】合并到【{1}】", request["right"], request["left"])))
        body = QHBoxLayout()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([str(tr(label)) for label in ("文件名称", "所在目录", "目标版本", "来源版本", "解决状态")])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.setColumnWidth(1, 200)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.tree.itemDoubleClicked.connect(lambda _item, _column: self._open_editor())
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        body.addWidget(self.tree, 1)
        actions = QVBoxLayout()
        self.left_button = QPushButton(tr("采用目标版本"))
        self.right_button = QPushButton(tr("采用来源版本"))
        self.merge_button = QPushButton(tr("手动合并"))
        for button in (self.left_button, self.right_button, self.merge_button):
            button.setMinimumWidth(150)
            button.setAutoDefault(False)
            actions.addWidget(button)
        self.left_button.clicked.connect(lambda: self._choose("left"))
        self.right_button.clicked.connect(lambda: self._choose("right"))
        self.merge_button.clicked.connect(self._open_editor)
        self.merge_button.setDefault(True)
        actions.addStretch()
        body.addLayout(actions)
        layout.addLayout(body, 1)
        self.group = QCheckBox(str(tr("按目录分组")))
        self.group.toggled.connect(self._populate)
        layout.addWidget(self.group)
        footer = QHBoxLayout()
        self.status = QLabel()
        footer.addWidget(self.status)
        footer.addStretch()
        self.finish = QPushButton(tr("完成并继续"))
        self.finish.clicked.connect(self._finish)
        cancel = QPushButton(tr("取消并回退"))
        cancel.clicked.connect(self._cancel)
        footer.addWidget(self.finish)
        footer.addWidget(cancel)
        layout.addLayout(footer)
        self._populate()
        if self._rows:
            self.tree.setCurrentItem(next(iter(self._rows.values())))

    @property
    def resolutions(self):
        return self.session.resolutions

    def _selected(self):
        return [item.data(0, Qt.ItemDataRole.UserRole) for item in self.tree.selectedItems() if item.data(0, Qt.ItemDataRole.UserRole) is not None]

    def _populate(self, *_args):
        selected = set(self._selected())
        self.tree.clear()
        self._rows = {}
        groups = {}
        for path, draft in self.session.files.items():
            name = PurePosixPath(path)
            directory = str(name.parent)
            parent = self.tree
            if self.group.isChecked():
                if directory not in groups:
                    group = QTreeWidgetItem(self.tree, [directory])
                    group.setFlags(group.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                    group.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
                    group.setExpanded(True)
                    groups[directory] = group
                parent = groups[directory]
            row = QTreeWidgetItem(parent, [name.name, directory, self._side_status(draft.item, 2), self._side_status(draft.item, 3), ""])
            row.setData(0, Qt.ItemDataRole.UserRole, path)
            row.setToolTip(0, path)
            row.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
            row.setSelected(path in selected)
            self._rows[path] = row
        self.tree.setRootIsDecorated(self.group.isChecked())
        self._refresh()

    def _side_status(self, item, side):
        stage = item["stages"].get(side)
        base = item["stages"].get(1)
        if stage is None:
            return str(tr("已删除"))
        if base is None:
            return str(tr("新增"))
        unchanged = stage["oid"] == base["oid"] and stage["mode"] == base["mode"]
        return str(tr("未修改" if unchanged else "已修改"))

    def _selection_changed(self):
        selected = self._selected()
        self.left_button.setEnabled(bool(selected))
        self.right_button.setEnabled(bool(selected))
        editable = len(selected) == 1 and self.session.files[selected[0]].item["text"]
        self.merge_button.setEnabled(editable)
        self.merge_button.setToolTip("" if editable or len(selected) != 1 else str(tr("二进制或特殊文件，请选择保留的一侧")))

    def _choose(self, side):
        for path in self._selected():
            self.session.files[path].choose_file(side)
            editor = self._editors.get(path)
            if editor is not None:
                editor.reload()
        self._refresh()

    def _reset_selected(self):
        paths = self._selected()
        if not paths or QMessageBox.question(self, tr("恢复文件冲突"), tr("恢复选中文件的初始冲突状态？当前合并草稿将被重置。"), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        for path in paths:
            self.session.files[path].reset()
            if path in self._editors:
                self._editors[path].reload()
        self._refresh()

    def _menu(self, point):
        row = self.tree.itemAt(point)
        if row is None or row.data(0, Qt.ItemDataRole.UserRole) is None:
            return
        if not row.isSelected():
            self.tree.clearSelection()
            self.tree.setCurrentItem(row)
        menu = QMenu(self)
        for label, handler, enabled in (("采用目标版本", lambda: self._choose("left"), True), ("采用来源版本", lambda: self._choose("right"), True), ("手动合并", self._open_editor, self.merge_button.isEnabled()), ("恢复文件冲突", self._reset_selected, True)):
            action = menu.addAction(str(tr(label)))
            action.setEnabled(enabled)
            action.triggered.connect(lambda _checked=False, callback=handler: callback())
        menu.exec(self.tree.viewport().mapToGlobal(point))
        menu.deleteLater()

    def _open_editor(self):
        selected = self._selected()
        if len(selected) != 1:
            return
        path = selected[0]
        if not self.session.files[path].item["text"]:
            QMessageBox.information(self, tr("手动合并"), tr("二进制或特殊文件，请选择保留的一侧"))
            return
        editor = self._editor_for(path)
        editor.show()
        editor.raise_()
        editor.activateWindow()

    def _editor_for(self, path):
        if path not in self._editors:
            from .conflict_editor import MergeEditor
            editor = MergeEditor(self.session, path, self)
            editor.changed.connect(self._refresh)
            editor.applied.connect(self._next_file)
            editor.navigation_requested.connect(self._navigate_file)
            self._editors[path] = editor
        return self._editors[path]

    def _navigate_file(self, current, direction):
        if self._finished:
            return
        paths = []
        iterator = QTreeWidgetItemIterator(self.tree)
        while iterator.value() is not None:
            path = iterator.value().data(0, Qt.ItemDataRole.UserRole)
            if path is not None:
                paths.append(path)
            iterator += 1
        if current not in paths:
            return
        start = paths.index(current)
        step = 1 if direction > 0 else -1
        # Cycle across the full list, including the current file only as a fallback.
        for offset in range(1, len(paths) + 1):
            path = paths[(start + step * offset) % len(paths)]
            draft = self.session.files[path]
            if not draft.item["text"] or draft.remaining == 0:
                continue
            source = self._editors[current]
            target = self._editor_for(path)
            self.tree.clearSelection()
            self.tree.setCurrentItem(self._rows[path])
            self.tree.scrollToItem(self._rows[path])
            if target is not source:
                maximized = source.isMaximized()
                target.setGeometry(source.normalGeometry() if maximized else source.geometry())
                source.hide()
                if maximized:
                    target.showMaximized()
                else:
                    target.showNormal()
                target.raise_()
                target.activateWindow()
            target.focus_edge(step)
            return

    def _next_file(self, current, advance):
        if not advance:
            return
        paths = list(self.session.files)
        start = paths.index(current) + 1
        for path in paths[start:] + paths[:start]:
            if self.session.files[path].resolution is None:
                self.tree.clearSelection()
                self.tree.setCurrentItem(self._rows[path])
                self.tree.scrollToItem(self._rows[path])
                if self.session.files[path].item["text"]:
                    self._open_editor()
                    self._editors[path].next_file.setChecked(True)
                return

    def _refresh(self):
        for path, row in self._rows.items():
            draft = self.session.files[path]
            state = "已解决" if draft.resolution is not None else "待应用" if draft.item["text"] and draft.remaining == 0 else "未解决"
            row.setText(4, str(tr(state)))
            icon = QStyle.StandardPixmap.SP_DialogApplyButton if draft.resolution is not None else QStyle.StandardPixmap.SP_MessageBoxWarning
            row.setIcon(4, self.style().standardIcon(icon))
        remaining = len(self.session.files) - len(self.resolutions)
        self.status.setText(tr("未解决文件：{0} / {1}", remaining, len(self.session.files)))
        self.finish.setEnabled(remaining == 0 and not self._finished)
        self._selection_changed()
        for editor in self._editors.values():
            editor._status()

    def _finish(self):
        if self._finished or len(self.resolutions) != len(self.session.files):
            return
        self._finished = True
        for editor in self._editors.values():
            editor.hide()
        self.accept()

    def _cancel(self):
        if self._finished:
            return
        if QMessageBox.question(self, tr("取消并回退"), tr("取消本次合并并回退当前操作？"), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self._finished = True
            for editor in self._editors.values():
                editor.hide()
            super().reject()

    def reject(self):
        for editor in self._editors.values():
            editor.hide()
        self.hide()

    def closeEvent(self, event):
        self.reject()
        event.ignore()
