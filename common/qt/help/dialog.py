"""Compact, scrollable explanation window using the shared text bindings."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialogButtonBox, QFrame, QScrollArea, QVBoxLayout, QWidget

from common.i18n.widgets import QDialog, QLabel


class HelpDialog(QDialog):
    def __init__(self, title: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(460, 340)
        self.setMinimumSize(340, 240)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(12)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.content = QLabel(text)
        self.content.setTextFormat(Qt.TextFormat.PlainText)
        self.content.setWordWrap(True)
        self.content.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.content.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        scroll.setWidget(self.content)
        layout.addWidget(scroll, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
