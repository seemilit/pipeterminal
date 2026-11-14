"""PipeTerminal window assembling the shared application shell."""

from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QSignalBlocker, Qt
from PySide6.QtGui import QCloseEvent, QKeySequence
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QMessageBox, QToolButton, QWidget

from common.i18n import tr
from common.i18n.widgets import QAction, QMainWindow
from common.modules.registry import ModuleRegistry
from common.qt.icons import create_icon
from common.qt.module_page import ModulePage
from common.qt.shell import ApplicationShell
from common.qt.window_state import WindowStateController

from common.i18n.errors import error_message


_WM_NCLBUTTONDBLCLK = 0x00A3
_HTSYSMENU = 3
_WM_SYSCOMMAND = 0x0112
_SC_DEFAULT = 0xF160
_REORDERABLE_DIRECTORIES = {"task", "connection", "log"}


class MainWindow(QMainWindow):
    def __init__(self, registry: ModuleRegistry, settings_path: Path | None = None) -> None:
        super().__init__()
        self.registry = registry
        self._module_pages: dict[str, QWidget] = {}
        registry.register_service("open_shell_panel", self._open_workflow_shell)
        registry.register_service("show_about", self._show_about)
        self._active_page: ModulePage | None = None
        self._current_module_id: str | None = None
        self.setWindowTitle("PipeTerminal")
        self.setMinimumSize(800, 520)
        self.resize(1100, 720)

        self.shell = ApplicationShell(self)
        self.setCentralWidget(self.shell)
        self.shell.sidebar.module_selected.connect(self._open_module)
        self.shell.sidebar.directory_panel.item_selected.connect(self._select_directory_item)
        self.shell.sidebar.directory_panel.item_activated.connect(self._activate_directory_item)
        self.shell.sidebar.directory_panel.order_changed.connect(self._save_directory_order)
        self.shell.bottom_panel.panel_activated.connect(self._activate_workspace_panel)

        self.file_actions: dict[str, QAction] = {}
        self._file_action_names: dict[str, str] = {}
        for action_id, name in (
            ("new", "新建"),
            ("rename", "重命名"),
            ("copy", "复制"),
            ("delete", "删除"),
            ("save", "保存"),
        ):
            action = QAction(tr(name), self)
            action.setIcon(create_icon(action_id))
            action.setEnabled(False)
            action.triggered.connect(
                lambda _checked=False, value=action_id: self._run_file_action(value)
            )
            self.file_actions[action_id] = action
            self._file_action_names[action_id] = name
            self.shell.toolbar.add_action(action)
        self.file_actions["save"].setShortcut(QKeySequence.StandardKey.Save)
        for action_id, name in (
            ("connect", "连接"),
            ("execute", "执行"), ("history", "历史版本"),
        ):
            action = QAction(tr(name), self)
            action.setEnabled(False)
            action.triggered.connect(lambda _checked=False, value=action_id: self._run_file_action(value))
            self.file_actions[action_id] = action
            self._file_action_names[action_id] = name

        self.sidebar_action = QAction(tr("左侧栏"), self)
        self.sidebar_action.setIcon(create_icon("sidebar"))
        self.sidebar_action.setCheckable(True)
        self.sidebar_action.setChecked(True)
        self.sidebar_action.toggled.connect(self.shell.sidebar.setVisible)

        self.bottom_panel_action = QAction(tr("显示交互窗口"), self)
        self.bottom_panel_action.setIcon(create_icon("bottom_panel"))
        self.bottom_panel_action.setCheckable(True)
        self.bottom_panel_action.setChecked(False)
        self.bottom_panel_action.toggled.connect(self._set_bottom_panel_visible)

        self.reset_layout_action = QAction(tr("重置布局"), self)
        self.reset_layout_action.setIcon(create_icon("reset_layout"))
        self.reset_layout_action.triggered.connect(self._reset_layout)

        self.shell.toolbar.add_action(self.file_actions["connect"], right=True, show_icon=False)
        self.shell.toolbar.add_action(self.bottom_panel_action, right=True, show_icon=False)
        run_button = self.shell.toolbar.add_action(self.file_actions["execute"], right=True, show_icon=False)
        run_button.setProperty("primary", True)
        self._stop_task_action = QAction(tr("停止"), self)
        self._stop_task_action.setVisible(False)
        self._stop_task_action.triggered.connect(self._stop_running_task)
        self._stop_task_button = self.shell.toolbar.add_action(self._stop_task_action, right=True, show_icon=False)
        self._stop_task_button.hide()
        self.shell.editor_toolbar.add_action(self.file_actions["history"], right=True, height=30, show_icon=False)
        self.shell.toolbar.addAction(self.sidebar_action)
        self.shell.toolbar.addAction(self.reset_layout_action)
        help_button = self.shell.toolbar.add_action(QAction(tr("帮助"), self), right=True, show_icon=False)
        help_menu = QMenu(help_button)
        # Older Premium appearance modules add their settings actions to this menu.
        self._help_menu = help_menu
        self.help_button = help_button
        about_action = QAction(tr("关于 PipeTerminal"), help_menu)
        about_action.triggered.connect(lambda: self._show_about())
        help_menu.addAction(about_action)
        help_button.setMenu(help_menu)
        help_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.shell.toolbar.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        self._window_state = WindowStateController(self, settings_path) if settings_path is not None else None
        if self._window_state is not None:
            self._window_state.restore_geometry()

    def _show_about(self, parent: QWidget | None = None) -> None:
        authorization = self.registry.authorization
        paid = self.registry.has_paid_features and authorization is not None and authorization.active_status == "valid"
        edition = tr("Plus 版" if paid else "免费版")
        version = QApplication.applicationVersion()
        dialog = QMessageBox(parent if parent is not None else self)
        dialog.setWindowTitle(tr("关于 PipeTerminal"))
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        dialog.setText(tr("版本 {0}", version) if version else tr("版本未知"))
        dialog.setInformativeText(tr("当前权限：{0}", edition))
        appearance = self.registry.get_service("window_appearance")
        if appearance is not None:
            appearance.decorate_about(dialog)
        dialog.exec()

    def load_modules(self) -> None:
        appearance = self.registry.get_service("window_appearance")
        if appearance is not None:
            appearance.attach(self, self._window_state.store if self._window_state is not None else None)
        for module in self.registry.get_sidebar_modules():
            self.shell.sidebar.add_module(
                module.id,
                tr(module.name),
                create_icon(module.icon or "module"),
                bottom=module.sidebar_position == "bottom",
                icon_name=module.icon or "module",
            )
        if self._window_state is not None:
            available = [
                module.id for module in self.registry.get_sidebar_modules()
                if module.sidebar_position == "top"
            ]
            module_id = self._window_state.initial_module_id(available)
            if module_id is not None:
                self._open_module(module_id)
            self._window_state.restore_layout()

    def _module_page(self, module_id: str):
        page = self._module_pages.get(module_id)
        if page is None:
            factory = self.registry.get(module_id).page_factory
            if factory is None:
                return
            page = factory()
            if not isinstance(page, QWidget):
                raise TypeError(tr("模块页面工厂必须返回 QWidget"))
            if isinstance(page, QDialog):
                page.setParent(self, Qt.WindowType.Dialog)
            elif not isinstance(page, ModulePage) or not page.uses_panel_workspace:
                self.shell.pages.add_page(module_id, page)
            bind_registry = getattr(page, "bind_registry", None)
            if callable(bind_registry):
                bind_registry(self.registry)
            if not isinstance(page, QDialog):
                if isinstance(page, ModulePage):
                    page.directory_changed.connect(lambda target=page: self._refresh_directory(target))
                    page.directory_item_renamed.connect(
                        lambda previous, name, module=module_id: self._rename_directory_item(module, previous, name)
                    )
                    page.actions_changed.connect(lambda target=page: self._update_file_actions(target))
                    page.status_changed.connect(
                        lambda message, target=page: self._set_page_status(target, message)
                    )
                    page.bottom_panel_requested.connect(self._show_bottom_panel)
                    page.bottom_panel_removed.connect(self._remove_bottom_panel)
                    page.panel_focus_requested.connect(self._request_panel_focus)
                    if page.uses_panel_workspace:
                        page.close_requested.connect(
                            lambda target=page: self._close_workspace_page(target)
                        )
            self._module_pages[module_id] = page
        return page

    def _open_workflow_shell(self, name, command, *, directory=""):
        page = self._module_page("connection")
        return page.open_workflow_shell(name, command, directory=directory)

    def _open_module(self, module_id: str, *, from_panel: bool = False) -> None:
        page = self._module_page(module_id)
        if page is None:
            return
        if isinstance(page, QDialog):
            page.show()
            page.raise_()
            page.activateWindow()
        else:
            if (not from_panel and self._active_page is not None and self._active_page is not page
                    and not self._active_page.uses_panel_workspace):
                if not self._active_page.can_leave():
                    self.shell.sidebar.set_active_module(self._current_module_id)
                    return
            self._current_module_id = module_id
            self._active_page = page if isinstance(page, ModulePage) else None
            if self.shell.panel_focus_mode:
                self._set_panel_focus_mode(False)
            self.shell.sidebar.set_active_module(module_id)
            workspace = isinstance(page, ModulePage) and page.uses_panel_workspace
            self.shell.set_workspace_mode(workspace)
            if workspace:
                self._show_workspace_page(module_id, page)
            else:
                self.shell.pages.show_page(module_id)
            if self._active_page is not None:
                self._active_page.activate()
                if self._window_state is not None:
                    self._window_state.restore_page(module_id, self._active_page)
            self._refresh_directory()
            self._update_file_actions()
            self._sync_layout_actions()

    def _show_workspace_page(self, module_id: str, page: ModulePage) -> None:
        bottom = self.shell.bottom_panel
        panel_id = "module." + module_id
        blocker = QSignalBlocker(bottom)
        if not bottom.has_panel(panel_id):
            bottom.add_panel(panel_id, page.windowTitle() or tr(self.registry.get(module_id).name), page)
        bottom.show_panel(panel_id)
        del blocker

    def _activate_workspace_panel(self, panel: QWidget) -> None:
        if not self.shell.workspace_mode or not isinstance(panel, ModulePage):
            return
        module_id = next((key for key, page in self._module_pages.items() if page is panel), None)
        if module_id is None:
            # Shell and SFTP tabs use the server configuration actions and directory.
            page = self._module_page("connection")
            if self._active_page is not page:
                self._active_page = page
                self._current_module_id = "connection"
                self.shell.sidebar.set_active_module("connection")
                self._refresh_directory()
                self._update_file_actions()
            return
        if panel is not self._active_page:
            self._open_module(module_id, from_panel=True)
        elif self.shell.panel_focus_mode:
            self._set_panel_focus_mode(False)

    def _close_workspace_page(self, page: ModulePage) -> None:
        if not page.can_leave():
            return
        panel_id = self.shell.bottom_panel.panel_id(page)
        if panel_id is None:
            return
        self._remove_bottom_panel(panel_id)
        if self._active_page is page:
            # Keep the cached editor and its output alive when its tab is closed.
            self._open_module("connection")

    def _refresh_directory(self, page: ModulePage | None = None) -> None:
        if page is not None and page is not self._active_page:
            return
        directory = self.shell.sidebar.directory_panel
        module_id = self._current_module_id
        if module_id is not None:
            directory.set_heading(tr(self.registry.get(module_id).name))
        reorderable = self._active_page is not None and module_id in _REORDERABLE_DIRECTORIES
        directory.set_reorder_enabled(reorderable)
        blocker = QSignalBlocker(directory.item_list)
        items = []
        if self._active_page is not None:
            items = self._active_page.directory_items()
        if reorderable and self._window_state is not None:
            items = self._window_state.order_directory_items(module_id, items)
        directory.set_items(items)
        if self._active_page is not None:
            directory.select_item(self._active_page.current_item_id())
        del blocker

    def _save_directory_order(self, order: list[str]) -> None:
        module_id = self._current_module_id
        if self._window_state is None or module_id not in _REORDERABLE_DIRECTORIES:
            return
        try:
            self._window_state.save_directory_order(module_id, order)
        except (OSError, ValueError) as exc:
            self._refresh_directory()
            QMessageBox.warning(self, tr("保存失败"), error_message(exc))

    def _rename_directory_item(self, module_id: str, previous_id: str, new_id: str) -> None:
        if self._window_state is not None:
            try:
                self._window_state.rename_directory_item(module_id, previous_id, new_id)
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, tr("保存失败"), error_message(exc))

    def _select_directory_item(self, item_id: str) -> None:
        if self._active_page is not None:
            selected = self._active_page.select_item(item_id)
            if selected and not self._active_page.uses_panel_workspace:
                self._set_bottom_panel_visible(False)
            self.shell.sidebar.directory_panel.select_item(self._active_page.current_item_id())

    def _activate_directory_item(self, item_id: str) -> None:
        if self._active_page is not None:
            self._active_page.activate_item(item_id)

    def _update_file_actions(self, page: ModulePage | None = None) -> None:
        task_page = self._module_pages.get("task")
        can_stop = isinstance(task_page, ModulePage) and task_page.is_action_enabled("stop")
        self._stop_task_action.setVisible(can_stop)
        self._stop_task_action.setEnabled(can_stop)
        self._stop_task_button.setVisible(can_stop)
        if page is not None and page is not self._active_page:
            return
        for action_id, action in self.file_actions.items():
            label = self._active_page.action_label(action_id) if self._active_page is not None else None
            action.setText(label if label is not None else tr(self._file_action_names[action_id]))
            tooltip = self._active_page.action_tooltip(action_id) if self._active_page is not None else None
            action.setToolTip(tooltip if tooltip is not None else action.text())
            action.setEnabled(
                not self.shell.panel_focus_mode
                and self._active_page is not None and self._active_page.is_action_enabled(action_id)
            )

    def _stop_running_task(self) -> None:
        task_page = self._module_pages.get("task")
        if isinstance(task_page, ModulePage) and task_page.is_action_enabled("stop"):
            task_page.file_actions["stop"]()

    def _run_file_action(self, action_id: str) -> None:
        page = self._active_page
        if not self.shell.panel_focus_mode and page is not None and page.is_action_enabled(action_id):
            handler = page.file_actions.get(action_id)
            if handler is not None:
                if not page.uses_panel_workspace and action_id != "connect":
                    self._set_bottom_panel_visible(False)
                handler()

    def _set_page_status(self, page: ModulePage, message: str) -> None:
        if page is self._active_page:
            self.shell.status_label.setText(message)

    def _set_bottom_panel_visible(self, visible: bool) -> None:
        visible = visible and self.shell.bottom_panel.has_panels()
        if visible:
            self.shell.set_workspace_mode(True)
            self._activate_workspace_panel(self.shell.bottom_panel.tabs.currentWidget())
        else:
            self._set_panel_focus_mode(False)
            if self._active_page is not None and self._active_page.uses_panel_workspace:
                self._open_module("connection", from_panel=True)
            else:
                self.shell.set_workspace_mode(False)
        self._sync_layout_actions()

    def _request_panel_focus(self, panel: QWidget, focused: bool) -> None:
        panel_id = self.shell.bottom_panel.panel_id(panel)
        if panel_id is None:
            return
        self.shell.set_workspace_mode(True)
        self.shell.bottom_panel.show_panel(panel_id)
        self._set_panel_focus_mode(focused)

    def _set_panel_focus_mode(self, focused: bool) -> None:
        self.shell.set_panel_focus_mode(focused)
        self._sync_layout_actions()
        self._update_file_actions()

    def _sync_layout_actions(self) -> None:
        for action, widget in (
            (self.sidebar_action, self.shell.sidebar),
            (self.bottom_panel_action, self.shell.bottom_panel),
        ):
            blocker = QSignalBlocker(action)
            action.setChecked(not widget.isHidden())
            del blocker
        self.sidebar_action.setEnabled(not self.shell.panel_focus_mode)
        self.bottom_panel_action.setEnabled(self.shell.bottom_panel.has_panels())
        self.bottom_panel_action.setText(
            tr("隐藏交互窗口") if self.shell.workspace_mode else tr("显示交互窗口")
        )

    def _show_bottom_panel(self, panel_id: str, name: str, panel: QWidget) -> None:
        bottom = self.shell.bottom_panel
        if not bottom.has_panel(panel_id):
            bottom.add_panel(panel_id, name, panel)
        self.shell.set_workspace_mode(True)
        bottom.show_panel(panel_id)
        self._sync_layout_actions()

    def _remove_bottom_panel(self, panel_id: str) -> None:
        self.shell.bottom_panel.remove_panel(panel_id)
        if not self.shell.bottom_panel.has_panels():
            self._set_bottom_panel_visible(False)
        else:
            self._sync_layout_actions()

    def closeEvent(self, event: QCloseEvent) -> None:
        if any(callable(getattr(page, "can_close", None)) and not page.can_close() for page in self._module_pages.values()):
            event.ignore()
            return
        if (self._active_page is not None and not self._active_page.uses_panel_workspace
                and not self._active_page.can_leave()):
            event.ignore()
            return
        if self._window_state is not None:
            try:
                self._window_state.save(self._current_module_id, self._module_pages)
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, tr("保存失败"), error_message(exc))
        super().closeEvent(event)

    def refresh_icons(self) -> None:
        for action_id, action in self.file_actions.items():
            action.setIcon(create_icon(action_id))
        self.sidebar_action.setIcon(create_icon("sidebar"))
        self.bottom_panel_action.setIcon(create_icon("bottom_panel"))
        self.reset_layout_action.setIcon(create_icon("reset_layout"))
        self.shell.sidebar.refresh_icons()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "reset_layout_action"):
            self.refresh_icons()

    def nativeEvent(self, event_type: QByteArray, message: int) -> object:
        if event_type == b"windows_generic_MSG":
            native_message = wintypes.MSG.from_address(int(message))
            if (
                native_message.message == _WM_NCLBUTTONDBLCLK
                and native_message.wParam == _HTSYSMENU
            ) or (
                native_message.message == _WM_SYSCOMMAND
                and native_message.wParam & 0xFFF0 == _SC_DEFAULT
            ):
                return True, 0
        return super().nativeEvent(event_type, message)

    def _reset_layout(self) -> None:
        self._set_panel_focus_mode(False)
        self.sidebar_action.setChecked(True)
        self.shell.reset_layout()
        self._sync_layout_actions()
        if self._window_state is not None:
            self._window_state.reset_layout()
