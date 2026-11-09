"""Lazy remote folder tree with one reader and bounded Qt rendering batches."""

import posixpath
import time
from collections import deque

from PySide6.QtCore import QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QVBoxLayout, QWidget

from common.i18n import tr
from common.i18n.widgets import QTreeWidgetItem

from .controller import TransferController
from .file_icons import RemoteFileIcons
from .drag_drop import RemoteTransferTree


class RemoteDirectoryTree(QWidget):
    directory_requested = Signal(str)
    context_requested = Signal(object, object)
    more_requested = Signal(str)
    invalidated = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(150)
        self.setMaximumWidth(280)
        self._connected = False
        self._closed = False
        self._items = {}
        self._cache = {}
        self._loaded = set()
        self._more = {}
        self._pending = deque()
        self._more_pending = deque()
        self._loading = None
        self._rendering = None
        self._current = "/"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tree = RemoteTransferTree()
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setResizeContentsPrecision(100)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemExpanded.connect(self._expanded)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(lambda point: self.context_requested.emit(self.tree, point))
        layout.addWidget(self.tree, 1)
        self._file_icons = RemoteFileIcons()
        self._folder_icon = self._file_icons.folder_icon()
        self._timer = QTimer(self)
        self._timer.setInterval(10)
        self._timer.timeout.connect(self._advance)
        self.controller = TransferController(self)
        self.controller.connection_changed.connect(self._connection_changed)
        self.controller.listing_ready.connect(self._listed)
        self.controller.listing_failed.connect(self._failed)
        self._connection_changed(False)

    def bind_session(self, session) -> None:
        self.controller.bind_session(session, "", "/")

    def _connection_changed(self, connected: bool) -> None:
        if self._closed:
            return
        self._connected = connected
        self._timer.stop()
        self._pending.clear()
        self._more_pending.clear()
        self._cache.clear()
        self._loaded.clear()
        self._more.clear()
        self._items.clear()
        self._rendering = None
        self._loading = "/" if connected else None
        self._current = "/"
        self.tree.clear()
        self.tree.setEnabled(connected)
        self._ensure_item("/")

    def _ensure_item(self, path: str):
        existing = self._items.get(path)
        if existing is not None:
            return existing
        item = QTreeWidgetItem([posixpath.basename(path.rstrip("/")) or "/"])
        item.setData(0, Qt.ItemDataRole.UserRole, path)
        item.setToolTip(0, path)
        item.setIcon(0, self._folder_icon)
        if path == "/":
            self.tree.addTopLevelItem(item)
        else:
            self._ensure_item(posixpath.dirname(path) or "/").addChild(item)
        placeholder = QTreeWidgetItem([""])
        placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
        item.addChild(placeholder)
        self._items[path] = item
        return item

    def _enqueue(self, path: str) -> None:
        if path in self._loaded or path in self._pending:
            return
        if path == self._loading and path not in self._cache:
            return
        if self._rendering is not None and self._rendering[0] == path:
            return
        self._pending.append(path)
        if self.isVisible() and self._connected:
            self._timer.start()

    def _expanded(self, item) -> None:
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path is not None:
            self._enqueue(path)

    def _clicked(self, item, _column) -> None:
        more = item.data(0, Qt.ItemDataRole.UserRole.value + 1)
        if more is not None:
            if more not in self._more_pending:
                self._more_pending.append(more)
            self._timer.start()
            return
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path is not None and self._connected:
            self.directory_requested.emit(path)

    def sync_directory(self, directory: str, entries, *, partial: bool = False) -> None:
        if not self._connected or not directory.startswith("/"):
            return
        directory = posixpath.normpath(directory)
        if self._loading == directory and not partial:
            self._cancel_loading()
        self._current = directory
        if not partial:
            self._cache[directory] = tuple(entry for entry in entries if entry.directory)
            self._loaded.discard(directory)
            self._more.pop(directory, None)
        blocker = QSignalBlocker(self.tree)
        selected = self._ensure_item(directory)
        path = "/"
        ancestors = [path]
        for name in directory.strip("/").split("/"):
            if name:
                path = posixpath.join(path, name)
                ancestors.append(path)
        for path in ancestors:
            self._items[path].setExpanded(True)
        self.tree.setCurrentItem(selected)
        self.tree.scrollToItem(selected)
        del blocker
        for path in ancestors:
            self._enqueue(path)

    def invalidate(self, directory: str) -> None:
        directory = posixpath.normpath(directory)
        self.invalidated.emit(directory)
        prefix = directory.rstrip("/") + "/"
        for path in tuple(self._more):
            if path == directory or path.startswith(prefix):
                self._more.pop(path, None)
                item = self._items.get(path)
                if item is not None:
                    for index in range(item.childCount() - 1, -1, -1):
                        if item.child(index).data(0, Qt.ItemDataRole.UserRole.value + 1) is not None:
                            item.takeChild(index)
        self._more_pending = deque(path for path in self._more_pending if path in self._more)
        if self._loading is not None and (self._loading == directory or self._loading.startswith(prefix)):
            path = self._cancel_loading()
            self._loaded.discard(path)
            self._enqueue(path)
        for path in tuple(self._cache):
            if path == directory or path.startswith(prefix):
                self._cache.pop(path, None)
                self._loaded.discard(path)
                self._more.pop(path, None)
        if self._rendering is not None:
            path = self._rendering[0]
            if path == directory or path.startswith(prefix):
                self._rendering = None
                self._enqueue(path)
        item = self._items.get(directory)
        if item is not None and item.isExpanded():
            self._enqueue(directory)

    def _cancel_loading(self):
        path, self._loading = self._loading, None
        self.controller.cancel_listing()
        return path

    def _listed(self, _directory: str, entries) -> None:
        path, self._loading = self._loading, None
        if path is not None and not self._closed:
            self._cache[path] = tuple(entry for entry in entries if entry.directory)
            self._more.pop(path, None)
            self._loaded.discard(path)
            self._enqueue(path)

    def _failed(self, _directory: str, error: str) -> None:
        path = _directory if _directory in self._items else self._loading
        if self._loading == path:
            self._loading = None
        item = self._items.get(path)
        if item is not None:
            item.setToolTip(0, tr("读取目录失败：{0}", error))
        if path in self._cache:
            self._enqueue(path)
        elif self.isVisible() and (self._pending or self._more_pending):
            self._timer.start()

    def _forget(self, item) -> None:
        for index in range(item.childCount()):
            self._forget(item.child(index))
        path = item.data(0, Qt.ItemDataRole.UserRole)
        self._items.pop(path, None)
        self._loaded.discard(path)
        self._cache.pop(path, None)
        self._more.pop(path, None)

    def begin_page(self, directory: str) -> None:
        self._loading = directory
        self.controller.begin_page(directory)

    def display_page(self, directory: str, entries, *, page: int, more: bool) -> None:
        if self._closed or not self._connected:
            return
        if self._loading == directory:
            self._loading = None
        self.controller.publish_page(directory, entries, notify=False)
        previous = self._cache.get(directory, ()) if page > 0 else ()
        combined = {entry.path: entry for entry in previous}
        combined.update((entry.path, entry) for entry in entries if entry.directory)
        self._cache[directory] = tuple(combined.values())
        self._more[directory] = more
        self._loaded.discard(directory)
        self._ensure_item(directory)
        self._enqueue(directory)
        if self.isVisible():
            self._timer.start()

    def selected_paths(self):
        return [path for item in self.tree.selectedItems() if (path := item.data(0, Qt.ItemDataRole.UserRole)) and path.strip("/")]

    def drop_directory(self, position):
        item = self.tree.itemAt(position)
        if item is not None:
            return item.data(0, Qt.ItemDataRole.UserRole) or item.data(0, Qt.ItemDataRole.UserRole.value + 1) or self._current
        return self._current

    def _begin_render(self, path: str, entries) -> None:
        item = self._items[path]
        item.setToolTip(0, path)
        desired = {entry.path for entry in entries}
        blocker = QSignalBlocker(self.tree)
        for index in range(item.childCount() - 1, -1, -1):
            child = item.child(index)
            child_path = child.data(0, Qt.ItemDataRole.UserRole)
            current_branch = child_path is not None and (
                self._current == child_path or self._current.startswith(child_path.rstrip("/") + "/")
            )
            if child_path is None or (child_path not in desired and not current_branch):
                self._forget(child)
                item.takeChild(index)
        del blocker
        self._rendering = (path, entries, 0)

    def _advance(self) -> None:
        if self._closed or not self._connected or not self.isVisible():
            self._timer.stop()
            return
        if self._rendering is None:
            if self._loading is None:
                while self._more_pending:
                    path = self._more_pending.popleft()
                    if path in self._items and self._more.get(path):
                        self.more_requested.emit(path)
                        return
            cached = next((
                path for path in self._pending
                if path in self._items and path not in self._loaded and path in self._cache
            ), None)
            if cached is not None:
                self._pending.remove(cached)
                self._begin_render(cached, self._cache[cached])
            elif self._loading is not None:
                self._timer.stop()
                return
            else:
                while self._pending:
                    path = self._pending.popleft()
                    if path not in self._items or path in self._loaded:
                        continue
                    self._loading = path
                    self._timer.stop()
                    self.controller.browse(path)
                    return
            if self._rendering is None:
                self._timer.stop()
                return
        path, entries, position = self._rendering
        if path not in self._items or self._cache.get(path) is not entries:
            self._rendering = None
            self._enqueue(path)
            return
        deadline = time.monotonic() + 0.004
        end = min(len(entries), position + 100)
        while position < end:
            self._ensure_item(entries[position].path)
            position += 1
            if time.monotonic() >= deadline:
                break
        self._timer.setInterval(10)
        if position == len(entries):
            self._loaded.add(path)
            self._rendering = None
            if self._more.get(path):
                more = QTreeWidgetItem([tr("加载更多…")])
                more.setData(0, Qt.ItemDataRole.UserRole.value + 1, path)
                self._items[path].addChild(more)
            selected = self._items.get(self._current)
            if selected is not None:
                self.tree.setCurrentItem(selected)
        else:
            self._rendering = (path, entries, position)

    def defer_rendering(self) -> None:
        if self.isVisible() and (self._rendering is not None or self._pending):
            self._timer.start(80)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._pending or self._more_pending or self._rendering is not None:
            self._timer.start()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def shutdown(self) -> None:
        self._closed = True
        self._timer.stop()
        self._pending.clear()
        self._more_pending.clear()
        self._rendering = None
        self.controller.shutdown()
