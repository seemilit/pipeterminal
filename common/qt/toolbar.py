"""Toolbar accepting actions from the shell and feature modules."""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFrame, QHBoxLayout, QToolButton, QToolTip, QWidget


class _ActionButton(QToolButton):
    def event(self, event):
        if event.type() == QEvent.Type.ToolTip and not self.isEnabled() and self.toolTip():
            QToolTip.showText(event.globalPos(), self.toolTip(), self)
            event.accept()
            return True
        return super().event(event)


class Toolbar(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("mainToolbar")
        self.setFrameShape(QFrame.Shape.NoFrame)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(0)
        self._left_layout = QHBoxLayout()
        self._left_layout.setSpacing(4)
        self._right_layout = QHBoxLayout()
        self._right_layout.setSpacing(6)
        layout.addLayout(self._left_layout)
        layout.addStretch(1)
        layout.addLayout(self._right_layout)

    def add_action(
        self, action: QAction, *, right: bool = False, height: int = 32, show_icon: bool = True,
    ) -> QToolButton:
        button = _ActionButton(self)
        button.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)
        button.setObjectName("editorActionButton" if height == 30 else "toolbarActionButton")
        button.setFixedHeight(height)
        button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon if show_icon else Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        button.setDefaultAction(action)
        target = self._right_layout if right else self._left_layout
        target.addWidget(button)
        return button
