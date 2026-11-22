"""Toolbar accepting actions from the shell and feature modules."""

from PySide6.QtCore import QEvent, QSize, Qt
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
    def __init__(self, parent: QWidget | None = None, *, collapse_when_empty: bool = False) -> None:
        super().__init__(parent)
        self._collapse_when_empty = collapse_when_empty
        self.setObjectName("mainToolbar")
        self.setFrameShape(QFrame.Shape.NoFrame)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(0)
        self._left_layout = QHBoxLayout()
        self._left_layout.setSpacing(4)
        self._right_layout = QHBoxLayout()
        self._right_layout.setSpacing(8)
        layout.addLayout(self._left_layout)
        layout.addStretch(1)
        layout.addLayout(self._right_layout)

    def sizeHint(self) -> QSize:
        if self._collapse_when_empty and self._left_layout.isEmpty() and self._right_layout.isEmpty():
            return QSize(0, 0)
        return super().sizeHint()

    def minimumSizeHint(self) -> QSize:
        if self._collapse_when_empty and self._left_layout.isEmpty() and self._right_layout.isEmpty():
            return QSize(0, 0)
        return super().minimumSizeHint()

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
