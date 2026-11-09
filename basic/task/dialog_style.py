"""Shared presentation for workflow parameter dialogs."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout
from common.i18n.widgets import QLabel


PARAMETER_SIDE_PADDING = 24


def parameter_dialog_layout(dialog, title, *, full_width=False):
    dialog.setWindowFlags(dialog.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint)
    dialog.setStyleSheet("""
        QDialog { background: palette(window); }
        QLabel#parameterHeading { font-size: 18px; font-weight: bold; padding-bottom: 8px; }
        QScrollArea { border: none; background: transparent; }
        QLineEdit, QComboBox, QSpinBox { min-height: 28px; padding: 3px 8px; }
        QPlainTextEdit { border: 1px solid palette(mid); border-radius: 6px; padding: 8px; background: palette(base); }
        QPushButton { min-height: 28px; padding: 3px 14px; }
        QPushButton#parameterConfirm:enabled { background: palette(highlight); color: palette(highlighted-text); border: 1px solid palette(highlight); border-radius: 5px; }
        QPushButton#parameterConfirm:hover:enabled { border-color: palette(window-text); }
        QRadioButton { padding: 6px 10px; }
    """)
    layout = QVBoxLayout(dialog)
    side_padding = 0 if full_width else PARAMETER_SIDE_PADDING
    layout.setContentsMargins(side_padding, 20, side_padding, 18)
    layout.setSpacing(16)
    heading = QLabel(title)
    heading.setObjectName("parameterHeading")
    heading.setWordWrap(True)
    if full_width:
        heading.setContentsMargins(PARAMETER_SIDE_PADDING, 0, PARAMETER_SIDE_PADDING, 0)
    layout.addWidget(heading)
    return layout
