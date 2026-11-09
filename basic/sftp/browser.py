"""Local Qt filesystem model and remote listings delivered by the controller."""

import posixpath
from pathlib import Path

from PySide6.QtCore import QDir, QEvent, Qt, Signal
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFileDialog, QFileSystemModel, QHBoxLayout, QMenu,
    QSplitter, QStackedWidget, QVBoxLayout, QWidget,
)

from common.i18n import tr
from common.i18n.errors import error_message
from common.i18n.widgets import QAction, QLabel, QPushButton

from .drag_drop import LocalTransferTree
from .file_page import RemoteFilePage
from .file_grid import FILE_VIEW_MODES
from .preferences import FileViewPreferences
from .path_bar import RemotePathBar
from .local_path_bar import LocalPathBar
from .navigation_history import DirectoryNavigationHistory
from .file_links import FileLinkDelegate, FileLinkHover


class LocalBrowser(QWidget):
    context_requested = Signal(object, object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._closed = False
        self._navigation = DirectoryNavigationHistory()
        self.directory = str(Path.home())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(tr("本地文件")))
        navigation = QHBoxLayout()
        up = QPushButton("↑")
        up.setToolTip(tr("上一级"))
        up.clicked.connect(lambda: self.open_directory(str(Path(self.directory).parent)))
        self.path = LocalPathBar()
        self.path.path_requested.connect(self.open_directory)
        choose = QPushButton(tr("选择目录"))
        choose.clicked.connect(self._choose_directory)
        navigation.addWidget(up)
        navigation.addWidget(self.path, 1)
        navigation.addWidget(choose)
        layout.addLayout(navigation)
        self.model = QFileSystemModel(self)
        self.model.setReadOnly(True)
        self.model.setFilter(QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.Hidden | QDir.Filter.NoDotAndDotDot)
        self.tree = LocalTransferTree()
        self.tree.setModel(self.model)
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setSortingEnabled(True)
        self.tree.setColumnWidth(0, 210)
        self.tree.doubleClicked.connect(self._activate)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(lambda point: self.context_requested.emit(self.tree, point))
        layout.addWidget(self.tree, 1)
        self.open_directory(self.directory)
        QApplication.instance().installEventFilter(self)

    def open_directory(self, directory: str, *, from_history: bool = False) -> None:
        path = Path(directory).expanduser()
        if path.is_dir():
            self.directory = str(path.resolve())
            self._navigation.commit(self.directory, from_history=from_history)
            self.path.record_path(self.directory)
            self.tree.setRootIndex(self.model.setRootPath(self.directory))
        else:
            self._navigation.cancel_pending()
            self.path.record_path(self.directory)

    def _move_history(self, step: int) -> None:
        directory = self._navigation.move(step)
        if directory is not None:
            self.path.close_popups()
            self.open_directory(directory, from_history=True)

    def eventFilter(self, watched, event) -> bool:
        if self._closed:
            return False
        if event.type() in {QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick, QEvent.Type.MouseButtonRelease}:
            if event.button() in {Qt.MouseButton.BackButton, Qt.MouseButton.ForwardButton} and isinstance(watched, QWidget):
                if self.isVisible() and (watched is self or self.isAncestorOf(watched)):
                    if event.type() != QEvent.Type.MouseButtonRelease:
                        self._move_history(-1 if event.button() == Qt.MouseButton.BackButton else 1)
                    event.accept()
                    return True
        return super().eventFilter(watched, event)

    def shutdown(self) -> None:
        self._closed = True
        QApplication.instance().removeEventFilter(self)
        self.path.shutdown()

    def _choose_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, tr("选择目录"), self.directory)
        if directory:
            self.open_directory(directory)

    def _activate(self, index) -> None:
        if self.model.isDir(index):
            self.open_directory(self.model.filePath(index))

    def selected_paths(self) -> list[str]:
        return [self.model.filePath(index) for index in self.tree.selectionModel().selectedRows(0)]

    def drop_directory(self, position) -> str:
        index = self.tree.indexAt(position)
        if index.isValid() and self.model.isDir(index):
            return self.model.filePath(index)
        return self.directory


class RemoteBrowser(QWidget):
    directory_requested = Signal(str)
    directory_selection_requested = Signal()
    tree_changed = Signal(object)
    readiness_changed = Signal()
    context_requested = Signal(object, object)
    shell_entry_requested = Signal(object)

    def __init__(self, parent=None, *, allow_directory_picker: bool = True, with_directory_tree: bool = False) -> None:
        super().__init__(parent)
        self._event_filter_ready = False
        self.directory = "."
        self._connected = False
        self._closed = False
        self._navigation = DirectoryNavigationHistory()
        self.ready = False
        self._selected_file = None
        self._page_cache = None
        self._directory_aliases = {}
        self._validated = False
        self._partial_listing = False
        self.refresh_handler = None
        self._cut_paths = frozenset()
        self._compact = False
        self._view_preferences = FileViewPreferences() if with_directory_tree else None
        saved_mode = self._view_preferences.read_mode() if self._view_preferences is not None else None
        self._view_mode = saved_mode or "details"
        self._view_mode_selected = saved_mode is not None
        self._view_wheel_delta = 0
        self._file_links = FileLinkHover(self)
        self._allow_view_modes = with_directory_tree
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(tr("服务器文件")))
        navigation = QHBoxLayout()
        self.navigation_layout = navigation
        self.back_button = QPushButton("←")
        self.forward_button = QPushButton("→")
        self.back_button.setToolTip(tr("后退"))
        self.forward_button.setToolTip(tr("前进"))
        self.back_button.clicked.connect(self.go_back)
        self.forward_button.clicked.connect(self.go_forward)
        for button in (self.back_button, self.forward_button):
            button.setFixedWidth(32)
            button.setStyleSheet("padding:0 4px; min-width:0;")
            button.setEnabled(False)
            button.hide()
        self.up = QPushButton("↑")
        self.up.setToolTip(tr("上一级"))
        self.up.clicked.connect(lambda: self.request_directory(posixpath.dirname(self.directory.rstrip("/")) or "/"))
        self.path = RemotePathBar()
        self.path.path_requested.connect(self.request_directory)
        self.refresh = QPushButton(tr("刷新"))
        self.refresh.clicked.connect(self.refresh_directory)
        navigation.addWidget(self.up)
        navigation.addWidget(self.path, 1)
        self.choose = None
        if allow_directory_picker:
            self.choose = QPushButton(tr("选择目录"))
            self.choose.clicked.connect(lambda _checked=False: self.directory_selection_requested.emit())
            navigation.addWidget(self.choose)
        navigation.addWidget(self.refresh)
        self.view_mode_button = QPushButton(tr(dict(FILE_VIEW_MODES)[self._view_mode]), self)
        self.view_mode_button.setToolTip(tr("显示方式（Ctrl＋滚轮切换）"))
        view_menu = QMenu(self.view_mode_button)
        view_group = QActionGroup(view_menu)
        view_group.setExclusive(True)
        self._view_actions = {}
        for mode, label in FILE_VIEW_MODES:
            action = QAction(tr(label), view_menu)
            action.setCheckable(True)
            action.setChecked(mode == self._view_mode)
            action.triggered.connect(lambda _checked=False, value=mode: self.set_view_mode(value))
            view_group.addAction(action)
            view_menu.addAction(action)
            self._view_actions[mode] = action
        self.view_mode_button.setMenu(view_menu)
        self.view_mode_button.setVisible(with_directory_tree)
        navigation.addWidget(self.view_mode_button)
        layout.addLayout(navigation)
        self._pages = QStackedWidget()
        self._default_page = self._create_page()
        self._page = self._default_page
        self.directory_tree = None
        if with_directory_tree:
            from .directory_tree import RemoteDirectoryTree

            self.directory_tree = RemoteDirectoryTree()
            self.directory_tree.tree.setItemDelegate(FileLinkDelegate(self.directory_tree.tree))
            self.directory_tree.tree.setMouseTracking(True)
            self.directory_tree.tree.viewport().installEventFilter(self)
            self._pages.setMinimumWidth(200)
            self.directory_tree.directory_requested.connect(self.request_directory)
            splitter = QSplitter(Qt.Orientation.Horizontal)
            splitter.setChildrenCollapsible(False)
            splitter.setHandleWidth(6)
            splitter.addWidget(self.directory_tree)
            splitter.addWidget(self._pages)
            splitter.setStretchFactor(0, 0)
            splitter.setStretchFactor(1, 1)
            splitter.setSizes([150, 650])
            layout.addWidget(splitter, 1)
        else:
            layout.addWidget(self._pages, 1)
        self.status = QLabel(tr("等待连接"))
        layout.addWidget(self.status)
        self._event_filter_ready = True
        QApplication.instance().installEventFilter(self)

    @property
    def tree(self):
        return self._page.view

    def bind_session(self, session) -> None:
        self.path.bind_session(session)
        if self.directory_tree is not None:
            self.directory_tree.bind_session(session)

    def bind_shell_navigation(self, allowed) -> None:
        self._file_links.allowed = allowed
        self._file_links.clear()

    def _update_navigation(self) -> None:
        available = self._connected and (self._validated or self._navigation.pending_directory is not None)
        self.back_button.setEnabled(available and self._navigation.can_go_back)
        self.forward_button.setEnabled(available and self._navigation.can_go_forward)

    def cancel_navigation(self) -> None:
        self._navigation.cancel_pending()
        self._update_navigation()

    def request_directory(self, directory: str) -> None:
        if self._closed or not self._connected:
            return
        self.cancel_navigation()
        self.directory_requested.emit(directory)

    def refresh_directory(self) -> None:
        if self.refresh_handler is None or not self.refresh_handler():
            self.request_directory(self.directory)

    def _move_history(self, step: int) -> None:
        if self._closed or not self._connected:
            return
        if not self._validated and self._navigation.pending_directory is None:
            return
        directory = self._navigation.move(step)
        if directory is not None:
            self.path.close_popups()
            self._update_navigation()
            self.directory_requested.emit(directory)

    def go_back(self) -> None:
        self._move_history(-1)

    def go_forward(self) -> None:
        self._move_history(1)

    def set_compact_view(self, compact: bool) -> None:
        if self._compact == compact:
            return
        self._compact = compact
        if not self._view_mode_selected:
            self.set_view_mode("list" if compact else "details", user_selected=False)

    def set_view_mode(self, mode: str, *, user_selected: bool = True) -> None:
        labels = dict(FILE_VIEW_MODES)
        if mode not in labels:
            return
        self._view_mode_selected |= user_selected
        if self._view_mode == mode:
            if user_selected:
                self._save_view_mode()
            return
        self._file_links.clear()
        self.tree.set_transfer_state(False, "")
        self._view_mode = mode
        self._page.set_view_mode(mode)
        self.tree.setEnabled(self.ready)
        self._view_actions[mode].setChecked(True)
        self.view_mode_button.setText(tr(labels[mode]))
        self.tree_changed.emit(self.tree)
        if user_selected:
            self._save_view_mode()

    def _save_view_mode(self) -> None:
        if self._view_preferences is None:
            return
        try:
            self._view_preferences.save_mode(self._view_mode)
        except (OSError, ValueError) as exc:
            self.status.setText(tr("保存显示方式失败：{0}", error_message(exc)))

    def eventFilter(self, watched, event) -> bool:
        if not getattr(self, "_event_filter_ready", False) or self._closed:
            return False
        if self._file_links.event_filter(watched, event):
            return True
        if event.type() in {QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick, QEvent.Type.MouseButtonRelease}:
            if event.button() in {Qt.MouseButton.BackButton, Qt.MouseButton.ForwardButton} and isinstance(watched, QWidget):
                if self.isVisible() and (watched is self or self.isAncestorOf(watched)):
                    if event.type() != QEvent.Type.MouseButtonRelease:
                        self.go_back() if event.button() == Qt.MouseButton.BackButton else self.go_forward()
                    event.accept()
                    return True
        if event.type() == QEvent.Type.Wheel and self._allow_view_modes and watched in (self._page.tree.viewport(), self._page.grid.viewport()):
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                delta = event.angleDelta().y() or event.pixelDelta().y() * 3
                self._view_wheel_delta += delta
                steps = int(self._view_wheel_delta / 120)
                if steps:
                    self._view_wheel_delta -= steps * 120
                    modes = [mode for mode, _label in FILE_VIEW_MODES]
                    index = max(0, min(len(modes) - 1, modes.index(self._view_mode) + steps))
                    self.set_view_mode(modes[index])
                event.accept()
                return True
            self._view_wheel_delta = 0
        return super().eventFilter(watched, event)

    @property
    def has_page_cache(self) -> bool:
        return self._page_cache is not None

    def cached_entries(self, directory):
        if not self._connected or not directory.startswith("/"):
            return None
        directory = self.canonical_directory(directory)
        if self._page_cache is not None:
            page = self._page_cache.get_fresh(directory)
            if page is not None:
                return page.entries
        if self._validated and not self._partial_listing and directory == self.directory:
            return self._page.entries
        return None

    def _create_page(self, prepare_hidden: bool = False):
        page = RemoteFilePage()
        page.prepare_hidden = prepare_hidden
        page.set_view_mode(self._view_mode)
        for view in (page.tree, page.grid):
            view.viewport().installEventFilter(self)
            view.itemDoubleClicked.connect(self._activate)
            view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            view.customContextMenuRequested.connect(lambda point, source=view: self.context_requested.emit(source, point))
        page.rendered.connect(self._page_rendered)
        self._pages.addWidget(page)
        return page

    def enable_page_cache(self, cache) -> None:
        self._page_cache = cache
        cache.page_removed.connect(self._remove_page)

    def disable_page_cache(self) -> None:
        if self._page_cache is None:
            return
        cache = self._page_cache
        cache.clear()
        cache.page_removed.disconnect(self._remove_page)
        self._page_cache = None
        self._directory_aliases.clear()
        self._activate_page(self._default_page)
        self.ready = self._validated = False
        self.tree.setEnabled(False)
        self.readiness_changed.emit()

    def _activate_page(self, page) -> None:
        page.set_view_mode(self._view_mode)
        page.set_cut_paths(self._cut_paths)
        if self._page_cache is not None:
            self._page_cache.pin(page)
        if self._page is not page:
            self._file_links.clear()
            self.tree.set_transfer_state(False, "")
            self._page = page
            self._pages.setCurrentWidget(page)
            self.tree_changed.emit(page.view)

    def _remove_page(self, page) -> None:
        if self._page is page:
            self.ready = self._validated = False
            self._activate_page(self._default_page)
        self._pages.removeWidget(page)
        page.shutdown()
        page.deleteLater()
        self.readiness_changed.emit()

    def _directory_page(self, directory):
        if self._page_cache is None:
            return self._default_page
        page = self._page_cache.get(directory)
        if page is None:
            page = self._create_page(True)
            self._page_cache.put(directory, page)
        return page

    def prepare_directory(self, directory: str) -> None:
        pending = self._navigation.pending_directory
        if pending is not None:
            if self.canonical_directory(directory) == self.canonical_directory(pending):
                return
            self.cancel_navigation()
        if self._page_cache is None or not directory.startswith("/"):
            return
        directory = posixpath.normpath(directory)
        self.ready = self._validated = False
        self.directory = directory
        self.path.setText(directory)
        page = self._page_cache.get(self._directory_aliases.get(directory, directory))
        if page is None:
            self._default_page.display_entries([])
            page = self._default_page
        self._activate_page(page)
        self.tree.setEnabled(False)
        if self.directory_tree is not None:
            self.directory_tree.sync_directory(directory, self._page.entries, partial=True)
        self.readiness_changed.emit()

    def prefetch_directory(self, snapshot) -> None:
        if self._page_cache is None:
            return
        page = self._directory_page(snapshot.directory)
        # Hover must not change the current path, selection or visible list.
        if page is self._page:
            return
        if page.entries != snapshot.entries:
            page.display_entries(snapshot.entries, incremental=True)
        self._page_cache.mark_fresh(snapshot.directory)

    def record_directory_alias(self, requested, directory: str) -> None:
        if requested:
            requested = posixpath.normpath(requested)
            if requested != directory:
                self._directory_aliases[requested] = directory
            else:
                self._directory_aliases.pop(requested, None)

    def canonical_directory(self, directory: str) -> str:
        directory = posixpath.normpath(directory)
        return self._directory_aliases.get(directory, directory)

    def _page_rendered(self) -> None:
        if self.sender() is not self._page:
            return
        if self._connected and self._validated and self._page.complete:
            self.ready = True
            self._page.tree.setEnabled(True)
            self._page.grid.setEnabled(True)
            self.readiness_changed.emit()

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        if not connected:
            self._file_links.clear()
        for widget in (self.up, self.path, self.refresh, self.tree):
            widget.setEnabled(connected)
        if self.choose is not None:
            self.choose.setEnabled(connected)
        if not connected:
            self._navigation.reset()
            self.path.reset_history()
            self.ready = self._validated = False
            if self._page_cache is not None:
                self._page_cache.clear()
            self._directory_aliases.clear()
            self._activate_page(self._default_page)
            self._default_page.display_entries([])
            self.tree.setEnabled(False)
        self._update_navigation()

    def display_directory(self, directory: str, entries, *, partial: bool = False) -> None:
        pending = self._navigation.pending_directory
        self._navigation.commit(directory, from_history=(
            pending is not None and self.canonical_directory(pending) == posixpath.normpath(directory)
        ))
        self.directory = directory
        self._partial_listing = partial
        self._activate_page(self._default_page if partial else self._directory_page(directory))
        self._validated = True
        self._update_navigation()
        self.path.record_path(directory)
        if self.directory_tree is not None:
            self.directory_tree.sync_directory(directory, entries, partial=partial)
        if self._page_cache is None or self._page.entries != tuple(entries):
            self._page.display_entries(entries, self._selected_file, incremental=self._page_cache is not None and not partial)
        else:
            self._page.select_file(self._selected_file)
        self._selected_file = None
        self.ready = self._page.complete
        self._page.tree.setEnabled(self.ready)
        self._page.grid.setEnabled(self.ready)
        if self._page_cache is not None and not partial:
            self._page_cache.mark_fresh(directory)
        self.readiness_changed.emit()

    def invalidate_directory(self, directory: str) -> None:
        if self._page_cache is not None:
            self._page_cache.invalidate(directory)
        if self.directory_tree is not None:
            self.directory_tree.invalidate(directory)
        prefix = posixpath.normpath(directory).rstrip("/") + "/"
        if self.directory == posixpath.normpath(directory) or self.directory.startswith(prefix):
            self.ready = self._validated = False
            self.tree.setEnabled(False)
            self.readiness_changed.emit()

    def listing_failed(self, directory: str, _error: str) -> None:
        history_request = self._navigation.pending_directory is not None
        self.cancel_navigation()
        if history_request:
            if self._page_cache is not None:
                self._page_cache.invalidate(self.canonical_directory(directory))
            if self.directory_tree is not None:
                self.directory_tree.invalidate(directory)
            self._validated = True
            self.ready = self._page_cache is None or self._page.complete
            self.tree.setEnabled(self.ready)
            self.path.record_path(self.directory)
            self._update_navigation()
            self.readiness_changed.emit()
            return
        if self._page_cache is not None:
            self.invalidate_directory(directory)
            if posixpath.normpath(directory) == self.directory:
                self._page.display_entries([], incremental=True)
            self.ready = self._validated = False
            self.tree.setEnabled(False)
            self.readiness_changed.emit()

    def begin_listing(self) -> None:
        self._file_links.clear()
        self.ready = self._validated = False
        self._update_navigation()
        self.tree.setEnabled(False)
        if self._page_cache is None:
            self.select_file(None)
        self.readiness_changed.emit()

    def select_file(self, path: str | None) -> None:
        self._selected_file = path

    def select_files(self, paths) -> None:
        self._selected_file = None
        self._page.select_files(paths)

    def set_cut_paths(self, paths) -> None:
        self._cut_paths = frozenset(paths)
        self._page.set_cut_paths(self._cut_paths)

    def defer_rendering(self) -> None:
        if self.directory_tree is not None:
            self.directory_tree.defer_rendering()
        for index in range(self._pages.count()):
            self._pages.widget(index).defer_rendering()

    def _activate(self, item, _column) -> None:
        entry = item.data(0, Qt.ItemDataRole.UserRole)
        if self.ready and entry is not None and entry.directory:
            self.request_directory(entry.path)

    def selected_paths(self) -> list[str]:
        return [item.data(0, Qt.ItemDataRole.UserRole).path for item in self.tree.selectedItems()]

    def drop_directory(self, position) -> str:
        item = self.tree.itemAt(position)
        entry = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        return entry.path if entry is not None and entry.directory else self.directory

    def shutdown(self) -> None:
        self._closed = True
        self._event_filter_ready = False
        self._file_links.clear()
        QApplication.instance().removeEventFilter(self)
        self.path.shutdown()
        if self._page_cache is not None:
            self._page_cache.clear()
        for index in range(self._pages.count()):
            self._pages.widget(index).shutdown()
        if self.directory_tree is not None:
            self.directory_tree.shutdown()
