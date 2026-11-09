"""Sidebar navigation independent of feature modules."""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from common.i18n.widgets import QToolButton

from .directory_panel import DirectoryPanel
from .icons import create_icon

from common.i18n import tr


class Sidebar(QFrame):
    module_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("moduleSidebar")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(190)
        self._items: dict[str, QToolButton] = {}
        self._icon_names: dict[str, str] = {}
        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._navigation = QWidget()
        self._navigation.setObjectName("moduleNavigation")
        self._navigation.setFixedWidth(80)
        navigation_layout = QVBoxLayout(self._navigation)
        navigation_layout.setContentsMargins(4, 10, 4, 10)
        navigation_layout.setSpacing(0)
        self._navigation_layout = QVBoxLayout()
        self._navigation_layout.setSpacing(5)
        navigation_layout.addLayout(self._navigation_layout)
        navigation_layout.addStretch(1)
        self._bottom_layout = QVBoxLayout()
        self._bottom_layout.setSpacing(5)
        navigation_layout.addLayout(self._bottom_layout)
        layout.addWidget(self._navigation)
        self.directory_panel = DirectoryPanel()
        layout.addWidget(self.directory_panel, 1)

    def add_module(
        self, module_id: str, name: str, icon: QIcon | None = None,
        *, bottom: bool = False, icon_name: str = "",
    ) -> None:
        if module_id in self._items:
            raise ValueError(tr("侧栏模块已存在：{0}", module_id))
        button = QToolButton()
        button.setText(name)
        button.setToolTip(name)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setObjectName("sidebarModuleButton")
        button.setIconSize(QSize(22, 22))
        if icon is not None:
            button.setIcon(icon)
        button.clicked.connect(
            lambda _checked=False: self._select_module(module_id)
        )
        self._items[module_id] = button
        self._icon_names[module_id] = icon_name
        if bottom:
            self._bottom_layout.addWidget(button)
        else:
            button.setCheckable(True)
            self._button_group.addButton(button)
            self._navigation_layout.addWidget(button)
        self._update_navigation_width()

    def _select_module(self, module_id: str) -> None:
        self.module_selected.emit(module_id)

    def set_active_module(self, module_id: str | None) -> None:
        if module_id in self._items and self._items[module_id].isCheckable():
            self._items[module_id].setChecked(True)

    def refresh_language(self, _language: str) -> None:
        self._update_navigation_width()

    def refresh_icons(self) -> None:
        for module_id, button in self._items.items():
            if self._icon_names[module_id]:
                button.setIcon(create_icon(self._icon_names[module_id]))

    def _update_navigation_width(self) -> None:
        width = max(
            80,
            *(button.fontMetrics().horizontalAdvance(button.text()) + 24
              for button in self._items.values()),
        )
        self._navigation.setFixedWidth(width)
        for button in self._items.values():
            button.setFixedWidth(width - 8)
