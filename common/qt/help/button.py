"""Small question-mark entry point for feature-owned explanations."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from common.i18n import render_text
from common.i18n.widgets import QPushButton

from .dialog import HelpDialog


class HelpButton(QPushButton):
    def __init__(self, title: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__("?", parent)
        self._help_title = title
        self._help_text = text
        self._dialog: HelpDialog | None = None
        self.setObjectName("helpButton")
        self.setFixedSize(24, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(title)
        self.setAccessibleName(render_text(title))
        self.clicked.connect(self.show_help)

    def show_help(self) -> None:
        self.setAccessibleName(render_text(self._help_title))
        if self._dialog is None:
            self._dialog = HelpDialog(self._help_title, self._help_text, self.window())
        self._dialog.open()
