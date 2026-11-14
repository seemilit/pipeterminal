"""Application settings and the public license-activation entry point."""

from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QVBoxLayout, QWidget

from common.i18n import tr
from common.i18n.widgets import QDialog, QGroupBox, QLabel, QLineEdit, QPushButton
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
        self.resize(640, 440)
        self._authorization = None
        layout = QVBoxLayout(self)
        group = QGroupBox(tr("授权"))
        self.authorization_group = group
        self.authorization_group.hide()
        content = QVBoxLayout(group)
        self.state = QLabel()
        self.development = QLabel()
        self.holder = QLabel()
        self.expiration = QLabel()
        self.restart = QLabel(tr("授权变化将在重启后生效"))
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
        layout.addStretch(1)
        self._refresh()

    def bind_registry(self, registry) -> None:
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
