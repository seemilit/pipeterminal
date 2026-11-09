"""Reusable remote-list page; all item creation stays in the Qt thread."""

import time
from datetime import datetime

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QPalette
from PySide6.QtWidgets import QAbstractItemView, QVBoxLayout, QWidget

from common.i18n import tr
from common.i18n.widgets import QTreeWidgetItem

from .drag_drop import RemoteTransferTree
from .file_grid import RemoteFileGrid
from .file_icons import RemoteFileIcons, file_type
from .file_links import FileLinkDelegate
from .model import format_size


class RemoteFilePage(QWidget):
    rendered = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.entries = ()
        self.prepare_hidden = False
        self._items = {}
        self._displayed = {}
        self._directory_lookup = None
        self._pending = None
        self._selected_file = None
        self._selected_files = None
        self._restore_scroll = None
        self._closed = False
        self._cut_paths = frozenset()
        self._view_mode = "details"
        self._file_icons = RemoteFileIcons()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tree = RemoteTransferTree()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels([tr("名称"), tr("大小"), tr("类型"), tr("修改时间")])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setItemDelegate(FileLinkDelegate(self.tree))
        self.tree.setMouseTracking(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setColumnWidth(0, 200)
        layout.addWidget(self.tree)
        self.grid = RemoteFileGrid(self.tree, self)
        layout.addWidget(self.grid)
        self.grid.hide()
        self._timer = QTimer(self)
        self._timer.setInterval(10)
        self._timer.timeout.connect(self._render_batch)

    @property
    def view(self):
        return self.tree if self._view_mode == "details" else self.grid

    def set_view_mode(self, mode: str) -> None:
        if self._view_mode == mode:
            return
        enabled = self.view.isEnabled()
        anchor = self.view.indexAt(QPoint(8, 8))
        self._view_mode = mode
        if mode != "details":
            self.grid.set_view_mode(mode)
        self.tree.setVisible(mode == "details")
        self.grid.setVisible(mode != "details")
        self.view.setEnabled(enabled)
        if anchor.isValid():
            self.view.scrollTo(anchor, QAbstractItemView.ScrollHint.PositionAtTop)

    @property
    def complete(self) -> bool:
        return self._pending is None

    def display_entries(self, entries, selected_file=None, *, incremental: bool = False) -> None:
        self._timer.stop()
        self._selected_file = selected_file
        self._restore_scroll = self.view.verticalScrollBar().value() if incremental and self.entries else None
        self.entries = tuple(entries)
        if selected_file is not None or not self.entries:
            self._selected_files = None
        self._directory_lookup = None
        if not incremental:
            self.tree.clear()
            self._items.clear()
            self._displayed.clear()
        self._pending = iter(self._changes())
        if self.isVisible() or self.prepare_hidden:
            self._timer.start()

    def _changes(self):
        paths, directories = set(), {}
        ambiguous = False
        for entry in self.entries:
            paths.add(entry.path)
            if entry.directory and not entry.link:
                directories[entry.name] = entry
            ambiguous = ambiguous or any(char.isspace() for char in entry.name)
            yield "prepare", None, None
        self._directory_lookup = {} if ambiguous else directories
        previous = []
        for path in self._items:
            previous.append(path)
            yield "prepare", None, None
        for path in previous:
            if path not in paths:
                yield "remove", path, None
            else:
                yield "prepare", None, None
        for index, entry in enumerate(self.entries):
            yield "update", index, entry

    def find_directory(self, name):
        if self._directory_lookup is None:
            return None
        return self._directory_lookup.get(name)

    def _render_batch(self) -> None:
        if self._closed or self._pending is None or (not self.isVisible() and not self.prepare_hidden):
            self._timer.stop()
            return
        self._timer.setInterval(10)
        deadline = time.monotonic() + 0.004
        changes = 0
        while changes < 100:
            try:
                action, position, entry = next(self._pending)
            except StopIteration:
                self._pending = None
                self._timer.stop()
                if self._view_mode != "details":
                    self.grid.refresh_layout(force=True)
                if self._selected_file is not None:
                    item = self._items.get(self._selected_file)
                    if item is not None:
                        self.view.scrollToItem(item)
                    self._selected_file = None
                elif self._restore_scroll is not None:
                    self.view.verticalScrollBar().setValue(self._restore_scroll)
                self._restore_scroll = None
                if self._selected_files is not None:
                    self._apply_file_selection()
                self.rendered.emit()
                return
            if action == "prepare":
                pass
            elif action == "remove":
                item = self._items.pop(position)
                self._displayed.pop(position, None)
                self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
                changes += 1
            else:
                item = self._items.get(entry.path)
                previous = self._displayed.get(entry.path)
                if item is None:
                    item = QTreeWidgetItem()
                    self._items[entry.path] = item
                    self.tree.insertTopLevelItem(position, item)
                elif previous is not None and previous.directory != entry.directory:
                    self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
                    self.tree.insertTopLevelItem(position, item)
                if previous != entry:
                    self._update_item(item, entry)
                    self._displayed[entry.path] = entry
                    changes += 1
                if entry.path == self._selected_file:
                    self.view.setCurrentItem(item)
                    self.view.scrollToItem(item)
                    self._restore_scroll = None
            if time.monotonic() >= deadline:
                break

    def _update_item(self, item, entry) -> None:
        try:
            modified = datetime.fromtimestamp(entry.modified).strftime("%Y-%m-%d %H:%M")
        except (ValueError, OSError, OverflowError):
            modified = "--"
        for column, text in enumerate((
            entry.name, "--" if entry.directory else format_size(entry.size),
            file_type(entry), modified,
        )):
            item.setText(column, text)
        item.setData(0, Qt.ItemDataRole.UserRole, entry)
        item.setIcon(0, self._file_icons.icon(entry))
        item.setToolTip(0, entry.path)
        self._set_cut_style(item, entry.path)

    def _set_cut_style(self, item, path):
        brush = QBrush(self.tree.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)) if path in self._cut_paths else QBrush()
        item.setForeground(0, brush)

    def set_cut_paths(self, paths):
        paths = frozenset(paths)
        changed = self._cut_paths ^ paths
        self._cut_paths = paths
        for path in changed:
            item = self._items.get(path)
            if item is not None:
                self._set_cut_style(item, path)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "_cut_paths"):
            for path in self._cut_paths:
                item = self._items.get(path)
                if item is not None:
                    self._set_cut_style(item, path)

    def select_file(self, path) -> None:
        self._selected_file = path
        if path is not None:
            self._selected_files = None
        item = self._items.get(path)
        if item is not None:
            self.view.setCurrentItem(item)
            self.view.scrollToItem(item)
            self._selected_file = None if self.complete else path

    def select_files(self, paths) -> None:
        self._selected_files = tuple(dict.fromkeys(paths))
        self._selected_file = None
        self._restore_scroll = None
        if self.complete:
            self._apply_file_selection()

    def _apply_file_selection(self) -> None:
        paths, self._selected_files = self._selected_files, None
        items = [self._items[path] for path in paths if path in self._items]
        if not items:
            if not paths:
                self.tree.clearSelection()
            return
        self.tree.clearSelection()
        if items:
            self.view.setCurrentItem(items[0])
            for item in items:
                item.setSelected(True)
            self.view.scrollToItem(items[0])

    def defer_rendering(self) -> None:
        if self._pending is not None:
            self._timer.start(80)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._pending is not None:
            self._timer.start(10)

    def hideEvent(self, event) -> None:
        if not self.prepare_hidden:
            self._timer.stop()
        super().hideEvent(event)

    def shutdown(self) -> None:
        self._closed = True
        self._timer.stop()
        self._pending = None
