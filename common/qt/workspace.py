"""Coordinate navigation, session lifetime, and the workspace views."""

from collections.abc import Callable
from dataclasses import dataclass
from weakref import WeakSet

from PySide6.QtCore import QObject, QSignalBlocker, QTimer, Qt
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QTreeWidgetItem, QWidget

from common.i18n import tr
from common.i18n.errors import error_message
from .icons import create_icon
from .module_page import ModulePage


@dataclass
class WorkspaceSession:
    identifier: str
    module_id: str
    item_id: str | None
    panel: QWidget
    icon: str
    group_title: str
    number: int | None
    close: Callable[[], None]
    title_slot: Callable[[str], None] | None = None
    background: bool = False


class WorkspaceController(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.shell = window.shell
        self.registry = window.registry
        self.module_id = None
        self.home_page = None
        self.active_session = None
        self._focus_preferences: WeakSet[QWidget] = WeakSet()
        self._focused_panel: QWidget | None = None
        self.sessions: dict[str, WorkspaceSession] = {}
        self._panel_ids = {}
        self._recent = {}
        self._numbers = {}
        self._directories = {}
        self._dirty_directories = set()
        self._groups = {}
        self._items = {}
        self._session_items = {}
        self._pending = None
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._click_timer.timeout.connect(self._open_pending)

        shell = self.shell
        shell.tabs.home_requested.connect(self.show_home)
        shell.tabs.panel_requested.connect(self.select_panel)
        shell.tabs.panel_close_requested.connect(self.close_panel)
        shell.tabs.panel_menu_requested.connect(shell.bottom_panel._show_tab_menu)
        shell.bottom_panel.panel_close_requested.connect(self.close_panel)
        shell.bottom_panel.panel_activated.connect(self._group_selected)
        shell.background_runs.clicked.connect(self._open_background)
        shell.workspace_add_button.clicked.connect(self._open_new_tab)
        shell.workspace_focus_button.clicked.connect(self._toggle_focus)
        shell.workspace_settings_button.clicked.connect(lambda: self.window._open_module("settings"))
        shell.workspace_settings_button.setIcon(create_icon("settings"))
        shell.sessions.setExpandsOnDoubleClick(False)
        shell.sessions.itemClicked.connect(self._item_clicked)
        shell.sessions.itemDoubleClicked.connect(self._item_double_clicked)
        shell.sessions.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        shell.sessions.customContextMenuRequested.connect(self._item_menu)

    def show_module(self, module_id, page, kind):
        if kind == "workspace":
            self.open_session("module." + module_id, page.windowTitle() or tr(self.registry.get(module_id).name),
                              page, module_id)
        else:
            self.module_id = module_id
            self.home_page = page if isinstance(page, ModulePage) else None
            self.shell.sidebar.set_active_module(module_id)
            self.shell.pages.show_page(module_id)
            self.show_home()

    def _cancel_pending(self):
        self._click_timer.stop()
        self._pending = None

    def show_home(self):
        self._cancel_pending()
        self.active_session = None
        self.shell.tabs.set_workspace_empty(False)
        self.window._set_panel_focus_mode(False)
        self.shell.set_workspace_mode(False)
        self._update_focus_layout()
        with QSignalBlocker(self.shell.tabs):
            self.shell.tabs.setCurrentIndex(0)
        self.window._update_file_actions()

    def select_panel(self, panel):
        identifier = self._panel_ids.get(panel)
        if identifier is not None:
            self.select_session(identifier)

    def select_session(self, identifier):
        self._cancel_pending()
        session = self.sessions.get(identifier)
        if session is None:
            return
        if session.background:
            self._mount(session)
        entering = not self.shell.workspace_mode
        self.shell.set_workspace_mode(True)
        bottom = self.shell.bottom_panel
        with QSignalBlocker(bottom):
            bottom.show_panel(identifier)
        self._set_active(session)
        if entering:
            self.refresh_directories()
        self.update_background()

    def _group_selected(self, panel):
        identifier = self._panel_ids.get(panel)
        if self.shell.workspace_mode and identifier is not None:
            self._set_active(self.sessions[identifier])

    def _set_active(self, session):
        identifier = session.identifier
        self.active_session = identifier
        self.shell.tabs.set_workspace_empty(False)
        self._recent.pop(identifier, None)
        self._recent[identifier] = None
        with QSignalBlocker(self.shell.tabs), QSignalBlocker(self.shell.sessions):
            self.shell.tabs.setCurrentIndex(self.shell.tabs.indexOf(session.panel))
            item = self._session_items.get(identifier)
            if item is not None:
                item.parent().setExpanded(True)
                self.shell.sessions.setCurrentItem(item)
        self._update_focus_layout()
        self.window._update_file_actions()

    def open_session(self, identifier, title, panel, module_id):
        session = self.sessions.get(identifier)
        if session is None:
            module_id = getattr(panel, "workspace_module_id", None) or module_id
            descriptor = self.registry.get(module_id)
            item_id = getattr(panel, "workspace_item_id", None)
            number = None
            if item_id is not None and getattr(panel, "workspace_numbered", False):
                key = (module_id, item_id)
                number = self._numbers.get(key, 0) + 1
                self._numbers[key] = number
            icon = getattr(panel, "workspace_icon", None) or descriptor.icon or "log"
            def close():
                if isinstance(panel, ModulePage):
                    self.window._close_session_tab(panel)
                else:
                    self.remove_session(identifier)
                    panel.close()

            directory = descriptor.workspace_directory
            group_title = directory.title if directory is not None else descriptor.name
            session = WorkspaceSession(identifier, module_id, item_id, panel, icon, group_title, number, close)
            self.sessions[identifier] = session
            self._panel_ids[panel] = identifier
            session.title_slot = lambda _title: self.update_session_title(identifier)
            panel.windowTitleChanged.connect(session.title_slot)
            connection = getattr(panel, "session", None)
            if connection is not None:
                connection.connected.connect(lambda: self.update_session_title(identifier))
                connection.disconnected.connect(lambda _message: self.update_session_title(identifier))
            self._mount(session, title)
            if self.shell.workspace_mode:
                with QSignalBlocker(self.shell.sessions):
                    self._sync_session_item(session)
        self.select_session(identifier)

    def _mount(self, session, title=None):
        panel = session.panel
        title = title or panel.windowTitle() or tr(session.group_title)
        session.background = False
        bottom = self.shell.bottom_panel
        with QSignalBlocker(self.shell.tabs), QSignalBlocker(bottom):
            self.shell.tabs.add_panel(panel, title)
            bottom.add_panel(session.identifier, title, panel)
        self.update_session_title(session.identifier)
        self._set_icon(session)

    def _set_icon(self, session):
        index = self.shell.tabs.indexOf(session.panel)
        if index >= 0:
            self.shell.tabs.setTabIcon(index, create_icon(session.icon))

    def _active_panel(self) -> QWidget | None:
        if self.shell.workspace_mode:
            session = self.sessions.get(self.active_session)
            return session.panel if session is not None else None
        return self.shell.pages.currentWidget() if self.module_id is not None else None

    def _panel_for_new_tab(self) -> ModulePage | None:
        session = self.sessions.get(self.active_session)
        panel = session.panel if session is not None and self.shell.workspace_mode else None
        return panel if isinstance(panel, ModulePage) and panel.can_duplicate_panel() else None

    def _open_new_tab(self) -> None:
        panel = self._panel_for_new_tab()
        if panel is not None:
            self.shell.bottom_panel.request_new_panel(panel)

    def _toggle_focus(self) -> None:
        panel = self._active_panel()
        if panel is not None:
            self.set_active_panel_focus(panel not in self._focus_preferences)

    def set_active_panel_focus(self, focused: bool) -> None:
        panel = self._active_panel()
        if panel is not None:
            if focused:
                self._focus_preferences.add(panel)
            else:
                self._focus_preferences.discard(panel)
        self._update_focus_layout()

    def _update_focus_layout(self) -> None:
        panel = self._active_panel()
        focused = panel is not None and panel in self._focus_preferences
        target = panel if focused else None
        self.shell.set_workspace_focus(focused, panel_status=getattr(target, "provides_focus_status", False))
        self.shell.bottom_panel.set_workspace_focus(focused and self.shell.workspace_mode)
        if target is not self._focused_panel:
            previous, self._focused_panel = self._focused_panel, target
            if isinstance(previous, ModulePage):
                previous.set_panel_focus(False)
            if isinstance(target, ModulePage):
                target.set_panel_focus(True)
        self._refresh_focus_button()
        self.shell.workspace_add_button.setVisible(self._panel_for_new_tab() is not None)
        self.window._sync_layout_actions()

    def _refresh_focus_button(self) -> None:
        available = self._active_panel() is not None
        self.shell.workspace_settings_button.setVisible(self.shell.workspace_mode or available)
        button = self.shell.workspace_focus_button
        button.setVisible(available)
        if available:
            focused = self._focused_panel is not None
            label = tr("退出专注模式" if focused else "进入专注模式")
            button.setText(label)
            button.setToolTip(label)
            button.setIcon(create_icon("workspace_unfocus" if focused else "workspace_focus"))

    def refresh_icons(self):
        self._refresh_focus_button()
        self.shell.workspace_settings_button.setIcon(create_icon("settings"))
        for session in self.sessions.values():
            self._set_icon(session)

    def _title(self, session):
        panel = session.panel
        title = panel.windowTitle() or tr(session.group_title)
        if session.number is not None:
            title = f"{title} #{session.number}"
        connection = getattr(panel, "session", None)
        if connection is None:
            return title, title
        connected = connection.state == "connected"
        return ("● " if connected else "○ ") + title, str(tr("{0} · {1}", title, tr("已连接" if connected else "未连接")))

    def update_session_title(self, identifier):
        session = self.sessions.get(identifier)
        if session is None:
            return
        title, tooltip = self._title(session)
        index = self.shell.tabs.indexOf(session.panel)
        if index >= 0:
            self.shell.tabs.setTabText(index, title)
            self.shell.tabs.setTabToolTip(index, tooltip)
        item = self._session_items.get(identifier)
        if item is not None:
            item.setText(0, title)
            item.setToolTip(0, tooltip)

    def close_panel(self, panel):
        session = self.sessions.get(self._panel_ids.get(panel))
        if session is not None:
            session.close()

    def remove_session(self, identifier):
        session = self.sessions.get(identifier)
        if session is None:
            return
        panel = session.panel
        session.background = isinstance(panel, ModulePage) and panel.workspace_background_active()
        bottom = self.shell.bottom_panel
        with QSignalBlocker(self.shell.tabs), QSignalBlocker(bottom):
            index = self.shell.tabs.indexOf(panel)
            if index >= 0:
                self.shell.tabs.removeTab(index)
            bottom.remove_panel(identifier)
        if not session.background:
            self._focus_preferences.discard(panel)
            self.sessions.pop(identifier)
            self._panel_ids.pop(panel)
            self._recent.pop(identifier, None)
            panel.windowTitleChanged.disconnect(session.title_slot)
            item = self._session_items.pop(identifier, None)
            if item is not None:
                item.parent().removeChild(item)
            group = self._groups.get(session.module_id)
            if group is not None and not group.childCount() and session.module_id not in self._directories:
                tree = self.shell.sessions
                tree.takeTopLevelItem(tree.indexOfTopLevelItem(group))
                del self._groups[session.module_id]
        if self.active_session == identifier:
            remaining = next((key for key in reversed(self._recent) if bottom.has_panel(key)), None)
            if remaining is None:
                self._cancel_pending()
                self.active_session = None
                self.shell.tabs.set_workspace_empty(True)
                with QSignalBlocker(self.shell.sessions):
                    self.shell.sessions.setCurrentItem(None)
                self._update_focus_layout()
                self.window._update_file_actions()
            else:
                self.select_session(remaining)
        self.update_background()

    def refresh_directories(self, module_id=None):
        if module_id is not None:
            self._dirty_directories.add(module_id)
        if not self.shell.workspace_mode:
            return
        tree = self.shell.sessions
        with QSignalBlocker(tree):
            for descriptor in self.registry.get_workspace_modules():
                key = descriptor.id
                directory = descriptor.workspace_directory
                if key in self._dirty_directories or key not in self._directories:
                    try:
                        self._directories[key] = directory.list_items()
                    except (OSError, ValueError):
                        self._directories.setdefault(key, [])
                        self._dirty_directories.add(key)
                    else:
                        self._dirty_directories.discard(key)
                self._sync_directory(key, directory.title)
            for session in self.sessions.values():
                self._sync_session_item(session)
            for key, item in list(self._items.items()):
                if key[1] not in self._directories.get(key[0], ()):
                    item.parent().removeChild(item)
                    del self._items[key]
            current = self._session_items.get(self.active_session)
            if current is not None:
                tree.setCurrentItem(current)

    def _group(self, module_id, title):
        group = self._groups.get(module_id)
        if group is None:
            group = QTreeWidgetItem(self.shell.sessions)
            group.setExpanded(True)
            self._groups[module_id] = group
        group.setText(0, tr(title))
        return group

    def _sync_directory(self, module_id, title):
        group = self._group(module_id, title)
        for position, name in enumerate(self._directories[module_id]):
            key = (module_id, name)
            item = self._items.get(key)
            if item is None:
                item = QTreeWidgetItem([name])
                item.setData(0, Qt.ItemDataRole.UserRole, key)
                group.insertChild(position, item)
                self._items[key] = item

    def _sync_session_item(self, session):
        key = (session.module_id, session.item_id)
        group = self._group(session.module_id, session.group_title)
        parent = self._items.get(key) if session.item_id in self._directories.get(session.module_id, ()) else None
        parent = parent if parent is not None else group
        item = self._session_items.get(session.identifier)
        if item is None:
            item = QTreeWidgetItem(parent)
            item.setData(0, Qt.ItemDataRole.UserRole, session.identifier)
            self._session_items[session.identifier] = item
        elif item.parent() is not parent:
            item.parent().removeChild(item)
            parent.addChild(item)
        self.update_session_title(session.identifier)

    def rename_item(self, module_id, previous, name):
        old_key = (module_id, previous)
        key = (module_id, name)
        number = self._numbers.pop(old_key, 0)
        self._numbers[key] = max(number, self._numbers.get(key, 0))
        for session in self.sessions.values():
            if (session.module_id, session.item_id) == old_key:
                session.item_id = name
                session.panel.workspace_item_id = name
                if session.number is not None and session.panel.windowTitle() == previous:
                    session.panel.setWindowTitle(name)
        if previous in self._directories.get(module_id, ()):
            item = self._items.get(old_key)
            if item is not None and key not in self._items:
                del self._items[old_key]
                self._items[key] = item
                item.setText(0, name)
                item.setData(0, Qt.ItemDataRole.UserRole, key)
        self.refresh_directories(module_id)

    def _item_clicked(self, item, _column):
        self._cancel_pending()
        key = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(key, str):
            self.select_session(key)
        elif isinstance(key, (tuple, list)):
            self._pending = tuple(key)
            self._click_timer.start(QApplication.doubleClickInterval())

    def _item_double_clicked(self, item, _column):
        self._cancel_pending()
        key = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(key, (tuple, list)):
            self._open_item(*key)
        elif key is None and item.childCount():
            item.setExpanded(not item.isExpanded())

    def _open_pending(self):
        key = self._pending
        self._pending = None
        if key is None or not self.shell.workspace_mode:
            return
        for identifier in reversed(self._recent):
            session = self.sessions[identifier]
            if (session.module_id, session.item_id) == key:
                self.select_session(identifier)
                return
        self._open_item(*key)

    def _open_item(self, module_id, item_id):
        try:
            directory = self.registry.get(module_id).workspace_directory
            if directory is not None:
                directory.open_item(self.window._module_page(module_id), item_id)
        except (KeyError, OSError, ValueError) as error:
            QMessageBox.warning(self.window, tr("操作失败"), error_message(error))

    def _item_menu(self, position):
        self._cancel_pending()
        tree = self.shell.sessions
        item = tree.itemAt(position)
        if item is None:
            return
        key = item.data(0, Qt.ItemDataRole.UserRole)
        menu = QMenu()
        if isinstance(key, (tuple, list)):
            module_id, item_id = key
            menu.addAction(tr("打开"), lambda: self._open_item(module_id, item_id))
            page = self.window._module_page(module_id)
            if isinstance(page, ModulePage):
                for label, callback, enabled in page.workspace_item_actions(item_id):
                    menu.addAction(tr(label), callback).setEnabled(enabled)
        elif isinstance(key, str) and (session := self.sessions.get(key)) is not None:
            if session.item_id in self._directories.get(session.module_id, ()):
                menu.addAction(tr("复制"), lambda: self._open_item(session.module_id, session.item_id))
            menu.addAction(tr("关闭"), lambda: self.close_panel(session.panel))
        if not menu.isEmpty():
            menu.exec(tree.viewport().mapToGlobal(position))

    def _background_sessions(self):
        return [session for session in self.sessions.values()
                if session.background and session.panel.workspace_background_active()]

    def update_background(self):
        count = len(self._background_sessions())
        self.shell.background_runs.setVisible(bool(count))
        self.shell.background_runs.setText(tr("后台任务 ({0})", count))

    def _open_background(self):
        sessions = self._background_sessions()
        if sessions:
            self.select_session(sessions[-1].identifier)

    def request_focus(self, panel, _focused):
        self.select_panel(panel)
