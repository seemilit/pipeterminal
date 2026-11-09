"""Native shell controls consuming only public configuration/terminal APIs."""

from pathlib import Path

from PySide6.QtCore import QEvent, QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QMessageBox, QSplitter, QVBoxLayout, QWidget

from basic.connection.api import ServerConfigStore
from basic.terminal.api import NativeTerminalWidget
from common.i18n import tr
from common.licensing.prompt import prompt_activation
from common.i18n.widgets import QLabel, QLineEdit, QPushButton
from common.qt.module_page import ModulePage

from .profile import ShellProfile
from .session import SSHSession
from .preferences import ShellPreferences
from .search_bar import TerminalSearchBar

from common.i18n.errors import error_message


class ShellPage(ModulePage):
    connection_requested = Signal(str)
    transfer_views_closed = Signal()

    def __init__(self, store: ServerConfigStore, known_hosts: Path) -> None:
        super().__init__()
        self.store = store
        self._names: list[str] = []
        self._configuration = None
        self._paths_configuration = None
        self._bound_name: str | None = None
        self._last_profile: ShellProfile | None = None
        self._log_service = None
        self._log_writer = None
        self._last_log_writer = None
        self._terminal_mode = False
        self._monitor = None
        self._monitor_width = 275
        self._preferences = ShellPreferences(known_hosts.with_name("settings.json"))
        self._monitor_visible = self._preferences.read_monitor_visible()
        self._sftp_factory = None
        self._sftp_windows = None
        self._transfer_dialog = None
        self._transfer_popup = None
        self._transfer_popups = []
        self._transfer_tasks_dialog = None
        self._file_panel_open = False
        self._path_navigation = None
        self._terminal_metadata = None
        self._directory_cache_manager = None
        self._command_policy = None
        self._authorization = None
        self.session = SSHSession(known_hosts, self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.connection_controls = QWidget()
        controls = QHBoxLayout(self.connection_controls)
        controls.setContentsMargins(6, 4, 6, 4)
        self.server_label = QLabel(tr("服务器："))
        controls.addWidget(self.server_label)
        self.servers = QComboBox()
        self.servers.setMinimumWidth(140)
        controls.addWidget(self.servers)
        controls.addWidget(QLabel(tr("默认路径")))
        self.paths = QComboBox()
        controls.addWidget(self.paths, 1)
        self.connect_button = QPushButton(tr("连接"))
        self.reconnect_button = QPushButton(tr("重连"))
        for button in (self.connect_button, self.reconnect_button):
            controls.addWidget(button)
            button.hide()
        layout.addWidget(self.connection_controls)
        header = QWidget()
        header.setObjectName("shellHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(6, 5, 6, 5)
        header_layout.setSpacing(8)
        self.target = QLabel()
        header_layout.addWidget(self.target)
        self.connection_status = QWidget()
        self._status_click_pending = False
        self.connection_status.setCursor(Qt.CursorShape.PointingHandCursor)
        status_layout = QHBoxLayout(self.connection_status)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(4)
        self.connection_indicator = QLabel()
        self.connection_indicator.setFixedSize(8, 8)
        status_layout.addWidget(self.connection_indicator)
        self.status = QLabel(tr("未连接"))
        status_layout.addWidget(self.status)
        header_layout.addWidget(self.connection_status)
        self.mode_button = QPushButton(tr("终端模式"))
        self.mode_button.clicked.connect(self._toggle_terminal_mode)
        self.monitor_button = QPushButton(tr("隐藏状态栏") if self._monitor_visible else tr("显示状态栏"))
        self.monitor_button.clicked.connect(self._toggle_monitor_visibility)
        self.monitor_button.hide()
        header_layout.addWidget(self.monitor_button)
        header_layout.addStretch(1)
        self.disconnect_button = QPushButton(tr("断开"))
        self.file_transfer_button = QPushButton(tr("文件传输"))
        self.transfer_tasks_button = QPushButton(tr("传输列表"))
        self.file_transfer_button.clicked.connect(self._open_file_transfer)
        self.transfer_tasks_button.clicked.connect(self._open_transfer_tasks)
        self.log_button = QPushButton(tr("日志"))
        self.log_button.clicked.connect(self._open_log)
        self.search_button = QPushButton(tr("查找"))
        self.search_button.setToolTip(tr("查找终端内容（Ctrl+F）"))
        self.search_button.clicked.connect(lambda: self.search_bar.open_search())
        for button in (self.file_transfer_button, self.transfer_tasks_button):
            button.setEnabled(False)
            button.setToolTip(tr("文件传输功能将在后续版本提供"))
        self.close_button = QPushButton(tr("关闭标签"))
        self.close_button.clicked.connect(self._request_close)
        for button in (
            self.mode_button, self.disconnect_button, self.file_transfer_button,
            self.transfer_tasks_button, self.search_button, self.log_button, self.close_button,
        ):
            header_layout.addWidget(button)
        self.disconnect_button.hide()
        self.close_button.hide()
        layout.addWidget(header)
        self.body_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.body_splitter.setChildrenCollapsible(False)
        self.body_splitter.splitterMoved.connect(self._remember_monitor_width)
        terminal_container = QWidget()
        container_layout = QVBoxLayout(terminal_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        terminal_content = QWidget()
        terminal_content.setMinimumHeight(120)
        terminal_layout = QVBoxLayout(terminal_content)
        self.terminal_layout = terminal_layout
        terminal_layout.setContentsMargins(0, 0, 0, 0)
        terminal_layout.setSpacing(0)
        self.terminal_file_splitter = QSplitter(Qt.Orientation.Vertical)
        self.terminal_file_splitter.setChildrenCollapsible(False)
        self.terminal_file_splitter.addWidget(terminal_content)
        self.terminal_file_splitter.setStretchFactor(0, 1)
        container_layout.addWidget(self.terminal_file_splitter, 1)
        self.body_splitter.addWidget(terminal_container)
        self.body_splitter.setStretchFactor(0, 1)
        layout.addWidget(self.body_splitter, 1)
        self.terminal = NativeTerminalWidget(self)
        self.terminal.setObjectName("shellTerminal")
        self.terminal.fileContextRequested.connect(self._show_terminal_file_menu)
        terminal_font = self.terminal.font()
        terminal_font.setPointSize(10)
        self.terminal.setFont(terminal_font)
        terminal_palette = self.terminal.palette()
        for role, color in (
            (QPalette.ColorRole.Base, "#111827"),
            (QPalette.ColorRole.Text, "#e5e7eb"),
            (QPalette.ColorRole.Highlight, "#374151"),
            (QPalette.ColorRole.HighlightedText, "#ffffff"),
        ):
            terminal_palette.setColor(role, QColor(color))
        self.terminal.setPalette(terminal_palette)
        self.search_bar = TerminalSearchBar(self.terminal, self)
        terminal_layout.addWidget(self.search_bar)
        terminal_layout.addWidget(self.terminal, 1)
        command_bar = QWidget()
        command_bar.setObjectName("shellCommandBar")
        command_layout = QHBoxLayout(command_bar)
        self.command_layout = command_layout
        command_layout.setContentsMargins(4, 5, 4, 5)
        command_layout.setSpacing(0)
        command_layout.addWidget(QLabel(tr("命令：")))
        self.command_entry = QLineEdit()
        self.command_entry.installEventFilter(self)
        self.terminal.installEventFilter(self)
        self.command_entry.returnPressed.connect(self._send_command)
        command_layout.addWidget(self.command_entry, 1)
        self.send_button = QPushButton(tr("发送"))
        self.send_button.clicked.connect(self._send_command)
        self.interrupt_button = QPushButton(tr("中断"))
        self.interrupt_button.clicked.connect(self._interrupt)
        self.clear_button = QPushButton(tr("清屏"))
        self.clear_button.clicked.connect(self.terminal.clear)
        self.directory_protection_button = QPushButton(tr("目录保护"))
        self.directory_protection_button.clicked.connect(self._manage_directory_protection)
        for button in (self.send_button, self.interrupt_button, self.clear_button, self.directory_protection_button):
            command_layout.addWidget(button)
        self.file_panel_button = QPushButton("▲")
        self.file_panel_button.setFixedWidth(32)
        self.file_panel_button.setToolTip(tr("文件"))
        self.file_panel_button.clicked.connect(self._toggle_file_panel)
        command_layout.addWidget(self.file_panel_button)
        terminal_layout.addWidget(command_bar)
        self.servers.currentIndexChanged.connect(self._load_selected_server)
        self.connect_button.clicked.connect(self._request_connect)
        self.disconnect_button.clicked.connect(self._handle_connection_action)
        self.reconnect_button.clicked.connect(self._reconnect)
        for widget in (self.connection_status, self.connection_indicator, self.status):
            widget.installEventFilter(self)
        self.terminal.binaryCommitted.connect(self._send_terminal_input)
        self.terminal.textCommitted.connect(lambda text: self._send_terminal_input(text.encode("utf-8")))
        self.terminal.terminalResized.connect(self.session.resize)
        self.session.dataReceived.connect(self.terminal.feed)
        self.session.dataEnded.connect(self.terminal.finish)
        self.session.connected.connect(self._connected)
        self.session.disconnected.connect(self._disconnected)
        self.session.errorOccurred.connect(self._error)
        self.session.hostKeyRequested.connect(self._confirm_host_key, Qt.ConnectionType.QueuedConnection)
        self._update_controls()

    def bind_registry(self, registry) -> None:
        super().bind_registry(registry)
        self._sftp_windows = registry.get_service("sftp")
        try:
            self.monitor_button.setEnabled(registry.get("monitor").page_factory is not None)
        except KeyError:
            self.monitor_button.setEnabled(False)
        if self._authorization is None:
            self._authorization = registry.get_service("authorization")
            if self._authorization is not None:
                self._authorization.changed.connect(self._authorization_changed)
        try:
            self._sftp_factory = registry.get("sftp").page_factory
        except KeyError:
            self._sftp_factory = None
        if self._sftp_factory is not None and self._path_navigation is None:
            from .path_navigation import PathNavigation

            self._path_navigation = PathNavigation(self.terminal, self.session, self)
            self._path_navigation.bind_registry(registry)
            self._path_navigation.directory_ready.connect(self._jump_directory)
            self._path_navigation.directory_changed.connect(self._show_directory)
            self._path_navigation.working_directory_changed.connect(self._follow_shell_directory)
            self._path_navigation.status_changed.connect(self.status.setText)
        if self._path_navigation is not None and self._terminal_metadata is None:
            from basic.sftp.file_operations.terminal_prefetch import TerminalEntryPrefetch

            self._terminal_metadata = TerminalEntryPrefetch(self.session.connection_context, self)
            self.terminal.fileHovered.connect(self._hover_terminal_file)
            self.session.disconnected.connect(self._terminal_metadata.reset)
        cache_provider = registry.get_service("terminal_directory_cache")
        if cache_provider is not None and self._path_navigation is not None and self._directory_cache_manager is None:
            self._directory_cache_manager = cache_provider.create_manager(self.session, self.terminal, self._cache_workspace, self)
            self._path_navigation.bind_page_cache(self._directory_cache_manager)
            self._path_navigation.working_directory_changed.connect(self._directory_cache_manager.change_directory)
        self._bind_command_policy()
        self._log_service = registry.get_service("log")
        if self._log_service is not None:
            self._log_service.register_producer(self.session.shutdown)
            self._log_service.write_failed.connect(self._log_write_failed, Qt.ConnectionType.QueuedConnection)
        self._update_controls()

    def activate(self) -> None:
        if self._bound_name is None and self.session.state == "idle":
            try:
                selected = self.servers.currentData()
                self._names = self.store.list_names()
                blocker = QSignalBlocker(self.servers)
                self.servers.clear()
                for name in self._names:
                    self.servers.addItem(name, name)
                if selected in self._names:
                    self.servers.setCurrentIndex(self.servers.findData(selected))
                del blocker
                self._load_selected_server()
                self.directory_changed.emit()
            except (OSError, ValueError) as exc:
                self._error(error_message(exc))
        self.terminal.fit()
        self.terminal.focus_terminal()

    def directory_items(self) -> list[tuple[str, str]]:
        return [(name, name) for name in self._names]

    def current_item_id(self) -> str | None:
        return self.servers.currentData()

    def select_item(self, item_id: str) -> bool:
        if self.session.state != "idle":
            return item_id == self.servers.currentData()
        index = self.servers.findData(item_id)
        if index >= 0:
            self.servers.setCurrentIndex(index)
            return True
        return False

    def _load_selected_server(self, _index: int = -1) -> None:
        self._configuration = None
        name = self.servers.currentData()
        if name is not None:
            try:
                self._configuration = self.store.load(name)
            except (OSError, ValueError) as exc:
                self._error(error_message(exc))
        self._populate_paths()
        self.directory_changed.emit()
        self._update_controls()

    def _populate_paths(self) -> None:
        self._paths_configuration = self._configuration
        self.paths.clear()
        self.paths.addItem(tr("登录目录"), None)
        if self._configuration is not None:
            valid_paths = []
            for index, entry in enumerate(self._configuration.access_paths):
                if entry.path.strip():
                    self.paths.addItem(entry.path, index)
                    valid_paths.append(index)
                    if entry.selected:
                        self.paths.setCurrentIndex(self.paths.count() - 1)
            if len(valid_paths) == 1 and self.paths.currentIndex() == 0:
                self.paths.setCurrentIndex(1)

    def set_configuration(self, name: str, configuration) -> None:
        changed = name != self._bound_name or configuration != self._paths_configuration
        self._bound_name = name
        self._configuration = configuration
        blocker = QSignalBlocker(self.servers)
        self.servers.clear()
        self.servers.addItem(name, name)
        del blocker
        self.server_label.hide()
        self.servers.hide()
        self.connection_controls.hide()
        if changed and self.session.state == "idle":
            self._populate_paths()
        self._update_controls()

    def open_workflow_command(self, command="", *, directory=""):
        if self._configuration is None or self._bound_name is None:
            raise ValueError(tr("请选择服务器配置"))
        profile = ShellProfile(
            self._bound_name, self._configuration, directory=directory or None, command=command or None,
        )
        profile.validate()
        self.panel_focus_requested.emit(self, True)
        self.activate()
        self._start_profile(profile)

    def connect_selected(self, path_index: int | None = None) -> None:
        self.panel_focus_requested.emit(self, self._preferences.read_terminal_mode())
        self.activate()
        if path_index is not None:
            if self._configuration != self._paths_configuration:
                self._populate_paths()
            index = self.paths.findData(path_index)
            if index < 0:
                self._error(tr("第 {0} 条访问位置缺少服务器目录", path_index + 1))
                return
            self.paths.setCurrentIndex(index)
            self._connect()
        elif self.session.state == "idle":
            self._connect()

    def shutdown(self) -> None:
        if self._command_policy is not None:
            self._command_policy.shutdown()
        if self._terminal_metadata is not None:
            self._terminal_metadata.shutdown()
        if self._directory_cache_manager is not None:
            self._directory_cache_manager.shutdown()
        if self._path_navigation is not None:
            self._path_navigation.shutdown()
        if self._transfer_tasks_dialog is not None:
            self._transfer_tasks_dialog.shutdown()
            self._transfer_tasks_dialog.deleteLater()
            self._transfer_tasks_dialog = None
        for dialog in tuple(self._transfer_popups):
            self._close_transfer_popup(dialog)
        if self._transfer_dialog is not None:
            self._transfer_dialog.shutdown()
            self._transfer_dialog.deleteLater()
            self._transfer_dialog = None
        if self._monitor is not None:
            self._monitor.shutdown()
        self.session.shutdown()
        self.terminal.shutdown()
        if self._log_service is not None:
            self._log_service.unregister_producer(self.session.shutdown)

    def can_close(self):
        return all(dialog is None or dialog.can_close() for dialog in (self._transfer_dialog, *self._transfer_popups))

    def has_transfer_views(self) -> bool:
        return bool(self._transfer_popups)

    def can_duplicate_panel(self) -> bool:
        return self._bound_name is not None

    def can_disconnect_panel(self) -> bool:
        return self.session.state != "idle"

    def disconnect_panel(self) -> None:
        self.session.disconnect_session()

    def _request_close(self):
        self.close_requested.emit()

    def _run_file_command(self, command):
        if self.session.state != "connected":
            return
        if self.command_entry.text().strip():
            self.status.setText(tr("输入框已有命令，本次未替换"))
            return
        if not self.terminal.engine.shell_ready:
            self.command_entry.setText(command)
            self.command_entry.setFocus()
            self.status.setText(tr("命令已填入输入框，请确认终端空闲后发送"))
            return
        if self.session.send((command + "\r").encode("utf-8")):
            self.terminal.focus_terminal()

    def _toggle_terminal_mode(self) -> None:
        self.panel_focus_requested.emit(self, not self._terminal_mode)
        try:
            self._preferences.save_terminal_mode(self._terminal_mode)
        except (OSError, ValueError) as exc:
            self.status.setText(tr("保存终端模式设置失败：{0}", error_message(exc)))

    def set_panel_focus(self, focused: bool) -> None:
        self._terminal_mode = focused
        self.mode_button.setText(tr("编辑模式") if focused else tr("终端模式"))
        self._apply_monitor_visibility()
        if self.isVisible():
            QTimer.singleShot(0, self.terminal.fit)
            self.terminal.focus_terminal()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._monitor_visible = self._preferences.read_monitor_visible()
        self._apply_monitor_visibility()

    def _toggle_monitor_visibility(self) -> None:
        if self._monitor_visible:
            self._remember_monitor_width(0, 0)
        self._monitor_visible = not self._monitor_visible
        self._apply_monitor_visibility()
        try:
            self._preferences.save_monitor_visible(self._monitor_visible)
        except (OSError, ValueError) as exc:
            self.status.setText(tr("保存状态栏设置失败：{0}", error_message(exc)))
        QTimer.singleShot(0, self.terminal.fit)

    def _apply_monitor_visibility(self) -> None:
        self.monitor_button.setText(tr("隐藏状态栏") if self._monitor_visible else tr("显示状态栏"))
        visible = self._terminal_mode and self._monitor_visible
        if visible and self.isVisible():
            self._ensure_monitor()
        self.monitor_button.setVisible(self._terminal_mode)
        if self._monitor is not None:
            self._monitor.setVisible(visible)
            self.body_splitter.setSizes(
                [self._monitor_width, max(1, self.body_splitter.width() - self._monitor_width)]
                if visible else [0, max(1, self.body_splitter.width())]
            )

    def _ensure_monitor(self) -> None:
        if self._monitor is not None:
            return
        registry = getattr(self, "registry", None)
        if registry is None:
            return
        try:
            factory = registry.get("monitor").page_factory
        except KeyError:
            return
        if factory is not None:
            self._monitor = factory()
            self._monitor.bind_session(self.session, self._log_service)
            self.body_splitter.insertWidget(0, self._monitor)
            self.body_splitter.setStretchFactor(0, 0)
            self.body_splitter.setStretchFactor(1, 1)

    def _remember_monitor_width(self, _position: int, _index: int) -> None:
        if self._monitor is not None and self._terminal_mode and not self._monitor.isHidden():
            self._monitor_width = max(220, min(400, self.body_splitter.sizes()[0]))

    def _send_command(self) -> None:
        command = self.command_entry.text()
        if self._command_policy is not None:
            decision = self._command_policy.handle_command(command)
            if decision:
                if decision == "handled":
                    self.command_entry.clear()
                return
        if command.strip() and self.session.send((command + "\r").encode("utf-8")):
            self.command_entry.clear()
            self.terminal.focus_terminal()

    def _send_terminal_input(self, data: bytes) -> None:
        if self._command_policy is None or not self._command_policy.handle_input(data):
            self.session.send(data)

    def _manage_directory_protection(self) -> None:
        if self.registry.get_service("directory_protection") is None:
            prompt_activation(self.registry, self, tr("目录保护"))
        elif self._command_policy is not None:
            self._command_policy.manage()

    def _bind_command_policy(self) -> None:
        if self._command_policy is None:
            provider = self.registry.get_service("directory_protection")
            if provider is not None:
                try:
                    self._command_policy = provider.create_manager(self)
                except (OSError, ValueError) as exc:
                    self.status.setText(error_message(exc))

    def _show_terminal_file_menu(self, reference, position, *, input_menu=None):
        navigation = self._path_navigation
        dialog = self._ensure_transfer_dialog() if navigation is not None and navigation.file_actions_allowed else None
        if dialog is None:
            if input_menu is not None:
                input_menu.aboutToHide.connect(input_menu.deleteLater)
                input_menu.popup(position)
            else:
                self.terminal.show_text_context_menu(position)
            return
        cwd = (
            navigation.current_directory if input_menu is not None
            else navigation.directory_for_reference(reference)
        )
        if input_menu is None:
            reference = navigation.contextual_reference(reference)
        dialog.workspace.file_actions_handler.show_terminal_menu(
            self.terminal, reference, cwd, position, input_menu, lambda: navigation.file_actions_allowed,
            metadata_cache=self._terminal_metadata.cache if self._terminal_metadata is not None else None,
        )

    def _hover_terminal_file(self, reference) -> None:
        if self._terminal_metadata is None:
            return
        navigation = self._path_navigation
        if navigation is None or not navigation.file_actions_allowed:
            self._terminal_metadata.hover(None, None)
            return
        reference = navigation.contextual_reference(reference)
        cwd = navigation.directory_for_reference(reference) if reference is not None else None
        self._terminal_metadata.hover(reference, cwd)

    def eventFilter(self, watched, event) -> bool:
        if watched in (self.connection_status, self.connection_indicator, self.status):
            if event.type() in {QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick, QEvent.Type.MouseButtonRelease} and event.button() == Qt.MouseButton.LeftButton:
                if event.type() == QEvent.Type.MouseButtonRelease:
                    pending, self._status_click_pending = self._status_click_pending, False
                    if pending and self.connection_status.isEnabled() and watched.rect().contains(event.position().toPoint()):
                        self._handle_connection_action()
                else:
                    self._status_click_pending = event.type() == QEvent.Type.MouseButtonPress
                event.accept()
                return True
        if watched is self.command_entry and event.type() == QEvent.Type.ContextMenu and self._path_navigation is not None and self._path_navigation.file_actions_allowed:
            from basic.terminal.paths import input_reference_at
            reference = input_reference_at(watched.text(), watched.cursorPositionAt(event.pos()))
            if reference is not None:
                self._show_terminal_file_menu(reference, event.globalPos(), input_menu=watched.createStandardContextMenu())
                return True
        if event.type() in {QEvent.Type.KeyPress, QEvent.Type.InputMethod}:
            if watched in (self.command_entry, self.terminal) and self._transfer_dialog is not None:
                self._transfer_dialog.workspace.remote.defer_rendering()
                for dialog in self._transfer_popups:
                    dialog.workspace.remote.defer_rendering()
        return super().eventFilter(watched, event)

    def _interrupt(self) -> None:
        if self._command_policy is not None:
            self._command_policy.handle_input(b"\x03")
        if self.session.send(b"\x03"):
            self.terminal.focus_terminal()

    def _handle_connection_action(self) -> None:
        if self.session.state != "idle":
            self.session.disconnect_session()
        else:
            self._request_connect()

    def _connect(self) -> None:
        if self._configuration is None:
            return
        index = self.paths.currentData()
        entry = self._configuration.access_paths[index] if index is not None else None
        profile = ShellProfile(
            self.servers.currentData(), self._configuration,
            entry.path if entry else None,
            entry.command if entry and entry.command_enabled else None,
        )
        self._start_profile(profile)

    def _request_connect(self) -> None:
        if self._bound_name is not None:
            self.connection_requested.emit(self._bound_name)
        else:
            self._connect()

    def _start_profile(self, profile: ShellProfile) -> None:
        try:
            profile.validate(include_files=False)
            self.session.disconnect_session()
            if self._transfer_dialog is not None:
                self._transfer_dialog.update_profile(profile.name, profile.directory, server_address=profile.configuration.ip_address)
            for dialog in self._transfer_popups:
                dialog.update_profile(profile.name, profile.directory, server_address=profile.configuration.ip_address)
            self.terminal.clear()
            if self._log_service is not None:
                self._log_writer = self._log_service.open_session("shell", profile.name)
                self._last_log_writer = self._log_writer
                self.log_button.setText(tr("日志"))
                self.log_button.setToolTip("")
                self._log_writer.event("connection", tr("正在连接：{0}", profile.name))
                configuration = profile.configuration
                self._log_writer.event("target", f"{configuration.username}@{configuration.ip_address}:{configuration.port}")
                self._log_writer.event("directory", profile.directory or tr("默认登录目录"))
                self.session.output_observer = self._log_writer.output
            self.session.resize(*self.terminal.terminal_size())
            self._last_profile = profile
            if self._command_policy is not None:
                self._command_policy.profile_changed()
            self.session.connect_profile(profile)
            self._last_profile = profile
            self.status.setText(tr("正在连接…"))
            self._update_controls()
        except (OSError, ValueError) as exc:
            self._error(error_message(exc))

    def _reconnect(self) -> None:
        if self._last_profile is not None and self.session.state == "idle":
            if self._bound_name is not None:
                self.connection_requested.emit(self._bound_name)
            else:
                self._start_profile(self._last_profile)

    def _connected(self) -> None:
        if self._log_writer is not None:
            self._log_writer.event("connection", tr("已连接"))
        self.status.setText(tr("已连接"))
        self._update_controls()
        self.terminal.focus_terminal()

    def _disconnected(self, _message: str) -> None:
        if self._log_writer is not None:
            if _message:
                self._log_writer.event("error", _message)
            self._log_writer.event("connection", tr("未连接"))
            self._log_writer.close()
            self._log_writer = None
        self.session.output_observer = None
        self.status.setText(tr("未连接"))
        self._update_controls()

    def _update_controls(self) -> None:
        self.log_button.setEnabled(self._log_service is not None and self._last_log_writer is not None)
        idle = self.session.state == "idle"
        self.servers.setEnabled(idle)
        self.paths.setEnabled(idle)
        self.connect_button.setEnabled(idle and self._configuration is not None)
        self.reconnect_button.setEnabled(idle and self._last_profile is not None)
        connection_action = (
            tr("重连") if idle and self._last_profile is not None
            else tr("连接") if idle else tr("断开")
        )
        self.disconnect_button.setText(connection_action)
        self.disconnect_button.setEnabled(not idle or self._configuration is not None)
        self.connection_status.setEnabled(self.disconnect_button.isEnabled())
        self.connection_status.setToolTip(connection_action)
        connected = self.session.state == "connected"
        indicator_color = "#22c55e" if connected else "#9ca3af"
        self.connection_indicator.setStyleSheet(f"background-color:{indicator_color}; border-radius:4px;")
        self.connection_indicator.setToolTip(connection_action)
        self.file_transfer_button.setEnabled(connected and self._sftp_factory is not None)
        self.file_panel_button.setEnabled(self._file_panel_open or (connected and self._sftp_factory is not None))
        self.transfer_tasks_button.setEnabled(
            self._transfer_dialog is not None or (connected and self._sftp_factory is not None)
        )
        if self._sftp_factory is not None:
            self.file_transfer_button.setToolTip("")
            self.transfer_tasks_button.setToolTip("")
        for control in (self.command_entry, self.send_button, self.interrupt_button):
            control.setEnabled(connected)
        configuration = (
            self._last_profile.configuration
            if not idle and self._last_profile is not None else self._configuration
        )
        self.target.setText(
            f"{configuration.username}@{configuration.ip_address}:{configuration.port}"
            if configuration is not None else ""
        )

    def _ensure_transfer_dialog(self, initial_snapshot=None):
        if self._transfer_dialog is None and self._sftp_factory is not None and self.session.state == "connected":
            dialog = self._sftp_factory()
            from basic.sftp.clipboard import get_clipboard

            get_clipboard().bind_registry(self.registry)
            dialog.workspace.transfer_controller.bind_registry(self.registry)
            dialog.workspace.transfer_controller.paid_transfer_requested.connect(self._prompt_paid_transfer, Qt.ConnectionType.QueuedConnection)
            dialog.setParent(self.window(), Qt.WindowType.Dialog)
            dialog.workspace.command_requested.connect(self._run_file_command)
            if self._terminal_metadata is not None:
                dialog.workspace.file_operations.directories_changed.connect(self._terminal_metadata.cache.invalidate)
                dialog.workspace.controller.directory_invalidated.connect(
                    lambda directory: self._terminal_metadata.cache.invalidate((directory,))
                )
            dialog.panel_state_changed.connect(self._set_file_panel_state)
            if self._directory_cache_manager is not None:
                dialog.workspace.enable_directory_cache(self._directory_cache_manager.cache)
            if self._command_policy is not None:
                self._command_policy.bind_workspace(dialog.workspace)
            profile = self._last_profile
            directory = profile.directory if profile is not None else None
            if self._path_navigation is not None and self._path_navigation.current_directory is not None:
                directory = self._path_navigation.current_directory
            dialog.bind_session(
                self.session, profile.name if profile is not None else self.servers.currentData(),
                directory, self._log_service, initial_snapshot,
                server_address=profile.configuration.ip_address if profile is not None else "",
            )
            if self._path_navigation is not None:
                dialog.workspace.remote.directory_requested.connect(self._path_navigation.cancel_activation)
                dialog.workspace.remote.bind_shell_navigation(lambda: self._path_navigation.file_actions_allowed)
                dialog.workspace.remote.shell_entry_requested.connect(self._path_navigation.activate_entry)
            self._transfer_dialog = dialog
            self._update_controls()
        return self._transfer_dialog

    def _prompt_paid_transfer(self) -> None:
        prompt_activation(self.registry, self, tr("跨设备文件复制"))

    def _ensure_transfer_popup(self):
        return self._transfer_popup or self._create_transfer_popup()

    def _create_transfer_popup(self, directory: str | None = None):
        source = self._ensure_transfer_dialog()
        if source is None:
            return None
        policy = self.registry.get_service("sftp_window_policy")
        if self._sftp_windows is not None and self._sftp_windows.has_windows and policy is None:
            if not prompt_activation(self.registry, self, tr("多个 SFTP 窗口"), alternative=tr("继续并替换原窗口")):
                return None
            if self._transfer_dialog is not source or self.session.state != "connected":
                return None
            policy = self.registry.get_service("sftp_window_policy")
        popup = source.create_popup(self.window())
        if self._command_policy is not None:
            self._command_policy.bind_workspace(popup.workspace)
        profile = self._last_profile
        if directory is None:
            directory = source.workspace.controller.requested_directory or source.workspace.remote.directory
        popup.bind_session(
            self.session, profile.name if profile is not None else self.servers.currentData(), directory,
            server_address=profile.configuration.ip_address if profile is not None else "",
        )
        popup.workspace.command_requested.connect(self._run_file_command)
        popup.bottom_panel_requested.connect(self.bottom_panel_requested)
        popup.bottom_panel_removed.connect(self.bottom_panel_removed)
        popup.panel_focus_requested.connect(self.panel_focus_requested)
        popup.view_closed.connect(lambda target=popup: self._close_transfer_popup(target))
        popup.new_panel_requested.connect(self.new_panel_requested.emit)
        popup.new_view_requested.connect(lambda target=popup: self._duplicate_file_transfer(target))
        self._transfer_popups.append(popup)
        self._transfer_popup = popup
        if self._sftp_windows is not None:
            if not self._sftp_windows.admit(popup, lambda target=popup: self._close_transfer_popup(target), policy):
                self._close_transfer_popup(popup)
                return None
        return popup

    def _duplicate_file_transfer(self, source):
        directory = source.workspace.controller.requested_directory or source.workspace.remote.directory
        dialog = self._create_transfer_popup(directory)
        if dialog is not None:
            dialog.show_panel()

    def _close_transfer_popup(self, dialog):
        if dialog not in self._transfer_popups:
            return
        if self._sftp_windows is not None:
            self._sftp_windows.remove(dialog)
        self._transfer_popups.remove(dialog)
        self._transfer_popup = self._transfer_popups[-1] if self._transfer_popups else None
        dialog.shutdown()
        dialog.deleteLater()
        if not self._transfer_popups:
            self.transfer_views_closed.emit()

    def _ensure_transfer_tasks_dialog(self):
        source = self._ensure_transfer_dialog()
        if source is None:
            return None
        if self._transfer_tasks_dialog is None:
            self._transfer_tasks_dialog = source.create_tasks_dialog(self.window(), anchor=self.transfer_tasks_button)
            self._transfer_tasks_dialog.remote_location_requested.connect(self._locate_upload)
        return self._transfer_tasks_dialog

    def _locate_upload(self, task) -> None:
        if self.session.state != "connected":
            return
        dialog = self._ensure_transfer_popup()
        if dialog is None or not dialog.workspace.transfer_controller.is_current_task(task):
            return
        if self._path_navigation is not None:
            self._path_navigation.cancel_activation()
        dialog.workspace.locate_upload(task)
        dialog.open_transfer()

    def _cache_workspace(self, directory: str):
        from basic.sftp.navigation import DirectorySnapshot

        dialog = self._ensure_transfer_dialog(DirectorySnapshot(directory, ()))
        return dialog.workspace if dialog is not None else None

    def _follow_shell_directory(self, directory: str) -> None:
        if self.session.state != "connected":
            return
        if self._command_policy is not None and not self._command_policy.allow_automatic_listing(directory):
            return
        if self._transfer_popup is not None:
            self._transfer_popup.workspace.browse_directory(directory)
        if self._directory_cache_manager is None and self._transfer_dialog is not None:
            self._transfer_dialog.workspace.browse_directory(directory)

    def _authorization_changed(self) -> None:
        self._bind_command_policy()
        if self._path_navigation is None:
            return
        self._path_navigation.bind_registry(self.registry)
        if self._directory_cache_manager is not None and self.registry.get_service("terminal_directory_cache") is None:
            self._path_navigation.unbind_page_cache()
            if self._transfer_dialog is not None:
                self._transfer_dialog.workspace.remote.disable_page_cache()
            manager, self._directory_cache_manager = self._directory_cache_manager, None
            manager.shutdown()
            self.session.command_names = ()
            directory = self._path_navigation.current_directory
            if directory is not None:
                self._follow_shell_directory(directory)

    def _jump_directory(self, snapshot) -> None:
        if self._path_navigation is not None:
            if self._path_navigation.send_directory(snapshot):
                self.terminal.scroll_to_bottom()
                self.terminal.focus_terminal()

    def _show_directory(self, snapshot) -> None:
        if self._command_policy is not None and self._command_policy.protected(snapshot.directory):
            self._command_policy.show_directory(snapshot.directory)
            return
        existing = self._transfer_dialog is not None
        dialog = self._ensure_transfer_dialog(snapshot)
        if dialog is None:
            return
        if existing:
            dialog.show_directory(snapshot)
        if self._directory_cache_manager is not None:
            dialog.workspace.remote.begin_listing()
            self._directory_cache_manager.change_directory(snapshot.directory, revalidate=True)
        self._show_file_panel(dialog)
        self.status.setText(tr("已连接"))

    def _show_file_panel(self, dialog) -> None:
        opened = self._file_panel_open
        if self.terminal_file_splitter.indexOf(dialog.workspace) < 0:
            workspace = dialog.embed_files(self.terminal_file_splitter)
            self.terminal_file_splitter.addWidget(workspace)
        else:
            dialog.workspace.show_files()
            dialog.workspace.show()
            self._set_file_panel_state(True)
        if not opened:
            self.terminal_file_splitter.setSizes([
                max(120, self.terminal_file_splitter.height() - 260), 260,
            ])

    def _set_file_panel_state(self, opened: bool) -> None:
        self._file_panel_open = opened
        self.file_panel_button.setText("▼" if opened else "▲")
        self._update_controls()
        QTimer.singleShot(0, self.terminal.fit)

    def _toggle_file_panel(self) -> None:
        if self._file_panel_open:
            if self._transfer_dialog is not None:
                self._transfer_dialog.hide_embedded()
            return
        if self._command_policy is not None and self._command_policy.show_file_panel():
            return
        dialog = self._ensure_transfer_dialog()
        if dialog is not None:
            self._show_file_panel(dialog)

    def _open_file_transfer(self) -> None:
        dialog = self._create_transfer_popup()
        if dialog is not None:
            dialog.open_transfer()

    def _open_transfer_tasks(self) -> None:
        dialog = self._ensure_transfer_tasks_dialog()
        if dialog is not None:
            dialog.show_tasks()

    def _open_log(self) -> None:
        if self._log_service is not None and self._last_log_writer is not None:
            try:
                if self._last_log_writer.error:
                    QMessageBox.warning(self, tr("日志"), tr("日志写入失败：{0}", self._last_log_writer.error))
                self._log_service.open_viewer(self._last_log_writer.path, self.window())
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, tr("日志"), error_message(exc))

    def _log_write_failed(self, path, message: str) -> None:
        if self._last_log_writer is not None and path == self._last_log_writer.path:
            self.log_button.setText(tr("日志（异常）"))
            self.log_button.setToolTip(tr("日志写入失败：{0}", message))

    def _confirm_host_key(self, request) -> None:
        if not request.cancelled.is_set():
            request.accepted = QMessageBox.question(
                self, tr("确认服务器主机密钥"),
                tr("服务器：{0}\n密钥类型：{1}\n指纹：{2}\n\n是否信任此主机密钥？", request.hostname, request.key_type, request.fingerprint),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            ) == QMessageBox.StandardButton.Yes
        request.completed.set()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange and hasattr(self, "paths") and self.paths.count():
            self.paths.setItemText(0, tr("登录目录"))

    def _error(self, message: str) -> None:
        if self._log_writer is not None:
            self._log_writer.event("error", message)
        self.status.setText(tr("连接失败"))
        QMessageBox.warning(self, tr("命令终端"), message)
        self._update_controls()
