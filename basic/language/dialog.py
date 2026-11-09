"""Language selection window with saved, immediate switching."""

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QComboBox, QDialogButtonBox, QMessageBox, QVBoxLayout, QWidget

from common.i18n import LANGUAGES, current_language, tr
from common.i18n.manager import get_manager
from common.i18n.widgets import QDialog, QFormLayout

from common.i18n.errors import error_message


class LanguageDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._manager = get_manager()
        self.setWindowTitle(tr("语言"))
        self.resize(280, 140)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.choices = QComboBox()
        for code, name in LANGUAGES.items():
            self.choices.addItem(name, code)
        form.addRow(tr("语言："), self.choices)
        layout.addLayout(form)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self._save_language)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def showEvent(self, event: QEvent) -> None:
        self.choices.setCurrentIndex(self.choices.findData(current_language()))
        super().showEvent(event)

    def _save_language(self) -> None:
        try:
            self._manager.set_language(self.choices.currentData())
        except OSError as exc:
            QMessageBox.critical(self, tr("保存失败"), tr("无法保存语言设置") + f"\n{error_message(exc)}")
            return
        self.accept()
