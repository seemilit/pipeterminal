"""Application settings and the public license-activation entry point."""

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QVBoxLayout, QWidget

from common.i18n import tr
from common.i18n.widgets import QCheckBox, QDialog, QGroupBox, QLabel, QLineEdit, QPushButton
from common.licensing.model import LicenseError

from common.i18n.errors import error_message


_STATUS_TEXT = {
    "free": "未激活", "valid": "授权有效", "expired": "授权已过期",
    "not_yet_valid": "授权尚未生效", "invalid": "授权码无效", "unconfigured": "尚未配置授权验证公钥",
}


class SettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("设置"))
        self.setObjectName("settingsDialog")
        self.resize(680, 560)
        self._authorization = None
        self._connection_preferences = None
        self._log_service = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        self.login_group = QGroupBox(tr("登录信息"))
        login_layout = QVBoxLayout(self.login_group)
        self.hide_username = QCheckBox(tr("隐藏登录账号"))
        self.hide_username.toggled.connect(self._save_username_visibility)
        login_layout.addWidget(self.hide_username)
        self.login_group.hide()
        layout.addWidget(self.login_group)
        group = QGroupBox(tr("授权"))
        self.authorization_group = group
        self.authorization_group.hide()
        content = QVBoxLayout(group)
        content.setSpacing(12)
        self.state = QLabel()
        self.development = QLabel()
        self.holder = QLabel()
        self.expiration = QLabel()
        self.restart = QLabel(tr("授权变化将在重启后生效"))
        self.restart.setObjectName("secondaryText")
        for label in (self.state, self.development, self.holder, self.expiration, self.restart):
            label.setWordWrap(True)
            content.addWidget(label)
        content.addWidget(QLabel(tr("授权码")))
        self.code = QLineEdit()
        self.code.setMaxLength(12000)
        self.code.setPlaceholderText(tr("请输入授权码"))
        content.addWidget(self.code)
        actions = QHBoxLayout()
        self.activate_button = QPushButton(tr("激活"))
        self.remove_button = QPushButton(tr("移除授权"))
        self.activate_button.clicked.connect(self._activate)
        self.remove_button.clicked.connect(self._remove)
        actions.addStretch(1)
        actions.addWidget(self.activate_button)
        actions.addWidget(self.remove_button)
        content.addLayout(actions)
        layout.addWidget(group)
        self.help_group = QGroupBox(tr("帮助"))
        help_layout = QHBoxLayout(self.help_group)
        self.about_button = QPushButton(tr("关于 PipeTerminal"))
        help_layout.addWidget(self.about_button)
        help_layout.addStretch(1)
        layout.addWidget(self.help_group)
        self.help_group.hide()
        self.diagnostics_group = QGroupBox(tr("诊断"))
        diagnostics_layout = QHBoxLayout(self.diagnostics_group)
        diagnostics = QPushButton(tr("查看诊断日志"))
        diagnostics.clicked.connect(self._open_diagnostics)
        diagnostics_layout.addWidget(diagnostics)
        diagnostics_layout.addStretch(1)
        self.diagnostics_group.hide()
        layout.addWidget(self.diagnostics_group)
        layout.addStretch(1)
        self._refresh()

    def bind_registry(self, registry) -> None:
        self._connection_preferences = registry.get_service("connection")
        self._log_service = registry.get_service("log")
        self.diagnostics_group.setVisible(self._log_service is not None)
        if self._connection_preferences is not None:
            with QSignalBlocker(self.hide_username):
                self.hide_username.setChecked(self._connection_preferences.read_username_hidden())
            self.login_group.show()
        show_about = registry.get_service("show_about")
        if show_about is not None:
            self.about_button.clicked.connect(lambda: show_about(self))
        appearance = registry.get_service("window_appearance")
        if appearance is not None:
            appearance.attach_settings(self, has_help=show_about is not None)
        self._authorization = registry.get_service("authorization") if registry.has_paid_features else None
        self.authorization_group.setVisible(self._authorization is not None)
        if self._authorization is not None:
            self._authorization.changed.connect(self._refresh)
        self._refresh()

    def _open_diagnostics(self) -> None:
        from app import crash_log
        from basic.log.browser import LogBrowserDialog
        from basic.log.store import LogStore

        service = self._log_service
        conf = service.store.directory.parent
        path = crash_log.crash_log_path or conf.parent / "logs" / "error.log"
        errors = LogStore(path.parent)
        task_logs = LogStore(conf / "task_history" / "logs")
        sources = {
            "应用报错": (lambda: [(path.name, path.name)] if path.is_file() else [], errors.read, errors.directory),
            "日志归档": (service.store.list_logs, service.store.read, service.store.directory),
            "旧任务日志": (task_logs.list_logs, task_logs.read, task_logs.directory),
        }
        dialog = LogBrowserDialog(
            tr("诊断"), service, sources, self, show_folder=True,
            deletions={"日志归档": (service.store.delete, service.is_active), "旧任务日志": (task_logs.delete, None)},
        )
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def _save_username_visibility(self, hidden: bool) -> None:
        if self._connection_preferences is None:
            return
        try:
            self._connection_preferences.save_username_hidden(hidden)
        except (OSError, ValueError) as error:
            with QSignalBlocker(self.hide_username):
                self.hide_username.setChecked(self._connection_preferences.read_username_hidden())
            QMessageBox.warning(self, tr("设置"), tr("操作失败：{0}", error_message(error)))

    def _refresh(self) -> None:
        manager = self._authorization
        self.activate_button.setEnabled(manager is not None)
        self.remove_button.setEnabled(manager is not None)
        if manager is None:
            self.state.setText(tr("授权不可用"))
            for label in (self.development, self.holder, self.expiration, self.restart):
                label.hide()
            return
        status = manager.active_status if manager.development is not None and not manager.restart_required else manager.saved_status
        self.state.setText(tr("授权状态：{0}", tr(_STATUS_TEXT[status])))
        self.development.setVisible(manager.development is not None)
        if manager.development is not None:
            mode = {"all": "全部功能", "free": "模拟免费", "licensed": "模拟有效", "expired": "模拟过期"}
            self.development.setText(tr("开发模式：{0}", tr(mode[manager.development.mode])))
        grant = manager.displayed_grant
        for label in (self.holder, self.expiration):
            label.setVisible(grant is not None)
        if grant is not None:
            self.holder.setText(tr("授权用户：{0}", grant.holder))
            self.expiration.setText(tr("到期时间：{0}", grant.expires_at.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")))
        self.restart.setVisible(manager.restart_required)

    def _activate(self) -> None:
        if self._authorization is None:
            return
        try:
            self._authorization.activate(self.code.text())
        except LicenseError as exc:
            QMessageBox.warning(self, tr("授权"), tr(_STATUS_TEXT.get(exc.reason, "授权码无效")))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, tr("授权"), tr("操作失败：{0}", error_message(exc)))
        else:
            self.code.clear()
            QMessageBox.information(self, tr("授权"), tr("授权已保存，请重启应用后生效"))

    def _remove(self) -> None:
        if self._authorization is None:
            return
        try:
            self._authorization.remove()
        except OSError as exc:
            QMessageBox.warning(self, tr("授权"), tr("操作失败：{0}", error_message(exc)))
        else:
            self.code.clear()
            QMessageBox.information(self, tr("授权"), tr("授权已移除，请重启应用后生效"))
