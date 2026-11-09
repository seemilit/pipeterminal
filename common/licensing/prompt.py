"""Activation entry point for user-triggered paid operations."""

from PySide6.QtWidgets import QInputDialog, QMessageBox

from common.i18n import tr
from common.i18n.errors import error_message

from .model import LicenseError


_ERROR_LABELS = {
    "expired": "授权已过期",
    "not_yet_valid": "授权尚未生效",
    "unconfigured": "尚未配置授权验证公钥",
}


def prompt_activation(registry, parent, feature, *, detail=None, alternative=None):
    """Offer activation, or return True if the user chose the free alternative."""
    authorization = registry.get_service("authorization") if registry is not None and registry.has_paid_features else None
    message = detail or tr("{0}需要付费授权", feature)
    title = tr("付费功能")
    if alternative is not None or authorization is None:
        box = QMessageBox(QMessageBox.Icon.Information, title, message, parent=parent)
        if authorization is None:
            box.setInformativeText(tr("请使用支持激活码的 PipeTerminal 发行包"))
        activate = box.addButton(tr("输入激活码"), QMessageBox.ButtonRole.ActionRole) if authorization is not None else None
        free = box.addButton(alternative, QMessageBox.ButtonRole.AcceptRole) if alternative is not None else None
        box.addButton(QMessageBox.StandardButton.Cancel if alternative is not None else QMessageBox.StandardButton.Ok)
        box.exec()
        clicked = box.clickedButton()
        box.deleteLater()
        if free is not None and clicked is free:
            return True
        if activate is None or clicked is not activate:
            return False
    while True:
        code, accepted = QInputDialog.getText(parent, title, tr("{0}\n请输入授权码", message))
        if not accepted:
            return False
        try:
            authorization.activate(code)
        except LicenseError as error:
            QMessageBox.warning(parent, title, tr(_ERROR_LABELS.get(error.reason, "授权码无效")))
        except (OSError, ValueError) as error:
            QMessageBox.warning(parent, title, tr("操作失败：{0}", error_message(error)))
            return False
        else:
            QMessageBox.information(parent, title, tr("授权已保存，请重启应用后生效"))
            return False
