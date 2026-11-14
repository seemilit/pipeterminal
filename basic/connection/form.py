"""Server configuration form with feature-owned access path rows."""

from PySide6.QtCore import QEvent, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QMessageBox, QScrollArea,
    QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from common.qt.file_dialog import choose_file
from common.i18n import tr
from common.i18n.errors import error_message
from common.i18n.widgets import QFormLayout, QLabel, QLineEdit, QPushButton, QToolButton
from common.qt.icons import create_icon

from .model import AccessPath, ConfigurationError, ServerConfiguration
from .path_row import AccessPathRow
from .preferences import ConnectionFormPreferences


class ServerConfigurationForm(QScrollArea):
    changed = Signal()
    path_connection_requested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self._loading = False
        self._path_rows: list[AccessPathRow] = []
        self._selected_path_row: AccessPathRow | None = None
        self._connection_available = True
        self._preferences = ConnectionFormPreferences()
        self._basic_parameters_visible = self._preferences.read_basic_parameters_visible()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setObjectName("serverConfigurationForm")
        page = QWidget()
        page.setObjectName("serverConfigurationPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(14)
        connection = QFrame()
        connection.setObjectName("serverConnectionCard")
        connection_layout = QVBoxLayout(connection)
        connection_layout.setContentsMargins(18, 14, 18, 18)
        connection_layout.setSpacing(14)
        connection_header = QHBoxLayout()
        connection_title = QLabel(tr("服务器连接"))
        connection_title.setObjectName("configurationSectionHeading")
        connection_header.addWidget(connection_title, 1)
        self.connection_toggle_button = QPushButton()
        self.connection_toggle_button.clicked.connect(self._toggle_basic_parameters)
        connection_header.addWidget(self.connection_toggle_button)
        connection_layout.addLayout(connection_header)
        self._connection_fields = QWidget()
        fields = QFormLayout(self._connection_fields)
        fields.setContentsMargins(0, 0, 0, 0)
        fields.setHorizontalSpacing(18)
        fields.setVerticalSpacing(10)
        connection_layout.addWidget(self._connection_fields)
        self.controls = {
            key: QLineEdit() for key in ("IP_ADDRESS", "USERNAME", "PASSWORD", "KEY_FILENAME")
        }
        address_row = QWidget()
        address_layout = QHBoxLayout(address_row)
        address_layout.setContentsMargins(0, 0, 0, 0)
        self.controls["IP_ADDRESS"].setMaximumWidth(300)
        self._address_stack, self._masked_address = self._endpoint_field(self.controls["IP_ADDRESS"], 300)
        address_layout.addWidget(self._address_stack, 1)
        address_layout.addWidget(QLabel(tr("SSH 端口")))
        self.port = QLineEdit("22")
        self.port.setFixedWidth(80)
        self._port_stack, self._masked_port = self._endpoint_field(self.port, 80)
        self._port_stack.setFixedWidth(80)
        address_layout.addWidget(self._port_stack)
        self._endpoint_privacy = None
        self.controls["IP_ADDRESS"].textChanged.connect(self._refresh_endpoint_fields)
        address_layout.addStretch(1)
        fields.addRow(tr("服务器地址"), address_row)
        username_row = QWidget()
        self._username_layout = QHBoxLayout(username_row)
        self._username_layout.setContentsMargins(0, 0, 0, 0)
        self._username_layout.setSpacing(4)
        self._username_layout.addWidget(self.controls["USERNAME"], 1, Qt.AlignmentFlag.AlignVCenter)
        fields.addRow(tr("登录账号"), username_row)
        auth_mode = QFrame()
        auth_mode.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        auth_mode.setFixedHeight(30)
        auth_layout = QHBoxLayout(auth_mode)
        auth_layout.setContentsMargins(0, 0, 0, 0)
        auth_layout.setSpacing(0)
        self.password_auth = QPushButton(tr("密码登录"))
        self.password_auth.setObjectName("authPasswordButton")
        self.key_auth = QPushButton(tr("私钥登录"))
        self.key_auth.setObjectName("authKeyButton")
        self._auth_group = QButtonGroup(self)
        self._auth_group.setExclusive(True)
        for button in (self.password_auth, self.key_auth):
            button.setCheckable(True)
            self._auth_group.addButton(button)
            auth_layout.addWidget(button)
        self.password_auth.setChecked(True)
        auth_layout.addStretch(1)
        fields.addRow(tr("认证方式"), auth_mode)
        self._password_label = QLabel(tr("登录密码"))
        password_row = QWidget()
        self._password_layout = QHBoxLayout(password_row)
        self._password_layout.setContentsMargins(0, 0, 0, 0)
        self._password_layout.setSpacing(4)
        self._password_layout.addWidget(self.controls["PASSWORD"], 1, Qt.AlignmentFlag.AlignVCenter)
        self.password_visibility_button = QToolButton()
        self.password_visibility_button.setObjectName("passwordVisibilityButton")
        self.password_visibility_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.password_visibility_button.setFixedSize(28, 28)
        self.password_visibility_button.setIconSize(QSize(16, 16))
        self._password_layout.addWidget(self.password_visibility_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.set_password_visibility_available(False)
        self._password_row = password_row
        fields.addRow(self._password_label, password_row)
        self._key_label = QLabel(tr("SSH 私钥"))
        key_row = QWidget()
        key_layout = QHBoxLayout(key_row)
        key_layout.setContentsMargins(0, 0, 0, 0)
        key_layout.addWidget(self.controls["KEY_FILENAME"], 1)
        browse = QPushButton(tr("选择文件"))
        browse.clicked.connect(self._choose_key)
        key_layout.addWidget(browse)
        self._key_row = key_row
        fields.addRow(self._key_label, key_row)
        layout.addWidget(connection)
        paths = QFrame()
        paths.setObjectName("serverAccessPathsCard")
        paths_layout = QVBoxLayout(paths)
        paths_layout.setContentsMargins(18, 14, 18, 18)
        paths_layout.setSpacing(14)
        header = QHBoxLayout()
        paths_title = QLabel(tr("默认访问位置"))
        paths_title.setObjectName("configurationSectionHeading")
        header.addWidget(paths_title)
        header.addStretch(1)
        add_button = QPushButton(tr("增加路径"))
        add_button.clicked.connect(lambda _checked=False: self.add_path())
        header.addWidget(add_button)
        paths_layout.addLayout(header)
        self._paths_layout = QVBoxLayout()
        self._paths_layout.setSpacing(8)
        paths_layout.addLayout(self._paths_layout)
        layout.addWidget(paths)
        layout.addStretch(1)
        self.setWidget(page)
        # The theme paints this page, including its transparent Plus variant.
        page.setAutoFillBackground(False)
        for control in self.controls.values():
            control.textChanged.connect(self._notify_changed)
        self.port.textChanged.connect(self._notify_changed)
        self.password_auth.toggled.connect(self._auth_changed)
        self.key_auth.toggled.connect(self._auth_changed)
        self._update_auth_visibility()
        self._apply_basic_parameters_visibility()

    @staticmethod
    def _endpoint_field(editor, width):
        stack = QStackedWidget()
        stack.setMaximumWidth(width)
        masked = QLineEdit()
        masked.setReadOnly(True)
        stack.addWidget(editor)
        stack.addWidget(masked)
        return stack, masked

    def bind_endpoint_privacy(self, privacy) -> None:
        if privacy is not None and self._endpoint_privacy is None:
            self._endpoint_privacy = privacy
            privacy.endpoint_visibility_changed.connect(self._refresh_endpoint_fields)
            self._refresh_endpoint_fields()

    def _refresh_endpoint_fields(self, *_args) -> None:
        privacy = self._endpoint_privacy
        hidden = privacy is not None and privacy.endpoint_hidden
        if hidden:
            self._masked_address.setText(privacy.display_host(self.controls["IP_ADDRESS"].text()))
            self._masked_port.setText(privacy.display_port(self.port.text()))
        self._address_stack.setCurrentIndex(int(hidden))
        self._port_stack.setCurrentIndex(int(hidden))

    def _toggle_basic_parameters(self) -> None:
        self._basic_parameters_visible = not self._basic_parameters_visible
        self._apply_basic_parameters_visibility()
        try:
            self._preferences.save_basic_parameters_visible(self._basic_parameters_visible)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, tr("配置"), tr("保存基本参数显示设置失败：{0}", error_message(exc)))

    def _apply_basic_parameters_visibility(self) -> None:
        self._connection_fields.setVisible(self._basic_parameters_visible)
        self.connection_toggle_button.setText(
            tr("收起") if self._basic_parameters_visible else tr("显示")
        )

    def set_configuration(self, configuration: ServerConfiguration) -> None:
        self.hide_password()
        self._loading = True
        try:
            for key, value in (
                ("IP_ADDRESS", configuration.ip_address), ("USERNAME", configuration.username),
                ("PASSWORD", configuration.password), ("KEY_FILENAME", configuration.key_filename),
            ):
                self.controls[key].setText(value)
            self.port.setText(str(configuration.port))
            self.password_auth.setChecked(configuration.auth_method == "PASSWORD")
            self.key_auth.setChecked(configuration.auth_method == "KEY")
            for row in self._path_rows:
                self._paths_layout.removeWidget(row)
                row.hide()
                row.deleteLater()
            self._path_rows.clear()
            self._selected_path_row = None
            for value in configuration.access_paths:
                self.add_path(value)
            self._update_auth_visibility()
        finally:
            self._loading = False

    def configuration(self) -> ServerConfiguration:
        try:
            port = int(self.port.text().strip())
        except ValueError:
            raise ConfigurationError(tr("PORT 必须在 1 到 65535 之间")) from None
        return ServerConfiguration(
            ip_address=self.controls["IP_ADDRESS"].text().strip(),
            port=port, username=self.controls["USERNAME"].text().strip(),
            auth_method="KEY" if self.key_auth.isChecked() else "PASSWORD",
            password=self.controls["PASSWORD"].text(),
            key_filename=self.controls["KEY_FILENAME"].text().strip(),
            access_paths=tuple(row.value() for row in self._path_rows),
        )

    def add_path(self, value: AccessPath | None = None) -> None:
        row = AccessPathRow(len(self._path_rows) + 1, value or AccessPath())
        row.changed.connect(self._notify_changed)
        row.default_selected.connect(self._select_default_path)
        row.remove_requested.connect(self._remove_path)
        row.connect_requested.connect(self._connect_path)
        row.row_selected.connect(self._select_path_row)
        row.connect_button.setVisible(self._connection_available)
        self._path_rows.append(row)
        self._paths_layout.addWidget(row)
        self._notify_changed()

    def set_connection_available(self, available: bool) -> None:
        self._connection_available = available
        for row in self._path_rows:
            row.connect_button.setVisible(available)

    def _connect_path(self, row: AccessPathRow) -> None:
        if row in self._path_rows:
            self.path_connection_requested.emit(self._path_rows.index(row))

    def _select_default_path(self, selected: AccessPathRow) -> None:
        for row in self._path_rows:
            if row is not selected:
                blocker = QSignalBlocker(row.selected)
                row.selected.setChecked(False)
                del blocker

    def _select_path_row(self, selected: AccessPathRow) -> None:
        if selected is self._selected_path_row or selected not in self._path_rows:
            return
        previous, self._selected_path_row = self._selected_path_row, selected
        for row in (previous, selected):
            if row is not None:
                row.setProperty("active", row is selected)
                for target in (row, *row.findChildren(QWidget)):
                    target.style().unpolish(target)
                    target.style().polish(target)
                    target.update()

    def _remove_path(self, row: AccessPathRow) -> None:
        if row is self._selected_path_row:
            self._selected_path_row = None
        self._path_rows.remove(row)
        self._paths_layout.removeWidget(row)
        row.hide()
        row.deleteLater()
        for index, remaining in enumerate(self._path_rows, start=1):
            remaining.position_label.setText(tr("位置 {0}", index))
        self._notify_changed()

    def _auth_changed(self, checked: bool) -> None:
        if checked:
            self._update_auth_visibility()
            self._notify_changed()

    def _update_auth_visibility(self) -> None:
        password_login = self.password_auth.isChecked()
        layout = self._password_layout if password_login else self._username_layout
        if layout.indexOf(self.password_visibility_button) < 0:
            hidden = self.password_visibility_button.isHidden()
            layout.addWidget(self.password_visibility_button, 0, Qt.AlignmentFlag.AlignVCenter)
            self.password_visibility_button.setVisible(not hidden)
        self._password_label.setVisible(password_login)
        self._password_row.setVisible(password_login)
        self._key_label.setVisible(not password_login)
        self._key_row.setVisible(not password_login)
        self.update_password_visibility()

    def set_password_visibility_available(self, available: bool) -> None:
        self.hide_password()
        self.password_visibility_button.setVisible(available)

    def hide_password(self) -> None:
        for field in self.credential_fields():
            field.setEchoMode(QLineEdit.EchoMode.Password)
        self.update_password_visibility()

    def credential_fields(self) -> tuple[QLineEdit, QLineEdit]:
        return self.controls["USERNAME"], self.controls["PASSWORD"]

    def update_password_visibility(self) -> None:
        revealed = self.controls["USERNAME"].echoMode() == QLineEdit.EchoMode.Normal
        label = tr(
            ("隐藏账号和密码" if revealed else "显示账号和密码")
            if self.password_auth.isChecked()
            else ("隐藏登录账号" if revealed else "显示登录账号")
        )
        self.password_visibility_button.setText(label)
        self.password_visibility_button.setToolTip(label)
        self.password_visibility_button.setIcon(create_icon("eye" if revealed else "eye_off"))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange and hasattr(self, "password_visibility_button"):
            self.update_password_visibility()

    def _choose_key(self) -> None:
        path, _filter = choose_file(
            self, tr("选择文件"), self.controls["KEY_FILENAME"].text(),
        )
        if path:
            self.controls["KEY_FILENAME"].setText(path)

    def _notify_changed(self, _value: object = None) -> None:
        if not self._loading:
            self.changed.emit()
