"""Directory list populated by the currently active feature."""

from PySide6.QtCore import QPoint, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QAction, QDrag
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from common.i18n.widgets import QLabel, QToolButton
from common.i18n import tr


class _DirectoryList(QListWidget):
    order_changed = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self._dragged_item: QListWidgetItem | None = None
        self.setDropIndicatorShown(True)

    def item_ids(self) -> list[str]:
        return [self.item(row).data(Qt.ItemDataRole.UserRole) for row in range(self.count())]

    def startDrag(self, _supported_actions) -> None:
        item = self.currentItem()
        if item is None:
            return
        drag = QDrag(self)
        drag.setMimeData(self.mimeData([item]))
        self._dragged_item = item
        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            self._dragged_item = None
            drag.deleteLater()

    def dropEvent(self, event) -> None:
        if event.source() is not self or self._dragged_item is None:
            event.ignore()
            return
        source = self.currentItem()
        if source is not self._dragged_item:
            event.ignore()
            return
        old_row = self.row(source)
        point = event.position().toPoint()
        index = self.indexAt(point)
        if index.isValid():
            new_row = index.row() + int(point.y() > self.visualRect(index).center().y())
        else:
            new_row = next(
                (row for row in range(self.count()) if point.y() < self.visualItemRect(self.item(row)).top()),
                self.count(),
            )
        if new_row > old_row:
            new_row -= 1
        if new_row != old_row:
            with QSignalBlocker(self):
                self.insertItem(new_row, self.takeItem(old_row))
                self.setCurrentItem(source)
            self.order_changed.emit(self.item_ids())
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()


class DirectoryPanel(QFrame):
    _ACTION_WIDTH = 24
    _ACTION_HEIGHT = 26

    item_selected = Signal(str)
    item_activated = Signal(str)
    order_changed = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("directoryPanel")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumWidth(140)
        self._items: dict[str, QListWidgetItem] = {}
        self._action_buttons: dict[QAction, QToolButton] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QWidget()
        header.setObjectName("directoryHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)
        heading_layout = QHBoxLayout()
        heading_layout.setContentsMargins(14, 10, 12, 4)
        self.heading = QLabel(tr("配置列表"))
        self.heading.setObjectName("directoryHeading")
        self.count_label = QLabel("0")
        self.count_label.setObjectName("directoryCount")
        heading_layout.addWidget(self.heading, 1)
        heading_layout.addWidget(self.count_label)
        header_layout.addLayout(heading_layout)
        action_bar = QWidget()
        action_bar.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._action_layout = QHBoxLayout(action_bar)
        self._action_layout.setContentsMargins(6, 0, 6, 6)
        self._action_layout.setSpacing(2)
        self._more_button = self._create_action_button()
        self._more_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._more_button.setText("⋯")
        self._more_button.setToolTip(tr("更多操作"))
        self._more_menu = QMenu(self._more_button)
        self._more_button.clicked.connect(self._show_more_actions)
        self._more_button.hide()
        self._action_layout.addWidget(self._more_button)
        self._action_layout.addStretch()
        header_layout.addWidget(action_bar)
        layout.addWidget(header)
        self.item_list = _DirectoryList()
        self.item_list.setObjectName("directoryList")
        self.item_list.setSpacing(3)
        self.item_list.currentItemChanged.connect(self._select_item)
        self.item_list.itemDoubleClicked.connect(self._activate_item)
        self.item_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.item_list.customContextMenuRequested.connect(self._show_item_menu)
        self.item_list.order_changed.connect(self.order_changed)
        layout.addWidget(self.item_list, 1)

    def _create_action_button(self) -> QToolButton:
        button = QToolButton()
        button.setObjectName("directoryActionButton")
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setIconSize(QSize(16, 16))
        button.setFixedSize(self._ACTION_WIDTH, self._ACTION_HEIGHT)
        return button

    def add_action(self, action: QAction) -> None:
        button = self._create_action_button()
        button.setDefaultAction(action)
        self._action_layout.insertWidget(len(self._action_buttons), button)
        self._action_buttons[action] = button
        action.changed.connect(self._update_action_overflow)
        self._update_action_overflow()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_more_menu"):
            self._update_action_overflow()

    def _update_action_overflow(self) -> None:
        actions = [action for action in self._action_buttons if action.isVisible()]
        margins = self._action_layout.contentsMargins()
        available = self.contentsRect().width() - margins.left() - margins.right()
        spacing = self._action_layout.spacing()
        slots = (available + spacing) // (self._ACTION_WIDTH + spacing)
        # Reserve the menu's slot while expanding so one action returns at a time.
        shown_count = len(actions) if len(actions) == 1 and slots >= 1 else max(0, slots - 1)
        shown, overflow = actions[:shown_count], actions[shown_count:]

        for action, button in self._action_buttons.items():
            button.setVisible(action in shown)
        if self._more_menu.actions() != overflow:
            self._more_menu.clear()
            self._more_menu.addActions(overflow)
        self._more_button.setVisible(bool(overflow))

    def _show_more_actions(self) -> None:
        self._more_menu.popup(self._more_button.mapToGlobal(QPoint(0, self._more_button.height())))

    def _show_item_menu(self, position: QPoint) -> None:
        item = self.item_list.itemAt(position)
        if item is None or not self._action_buttons:
            return
        item_id = item.data(Qt.ItemDataRole.UserRole)
        self.item_list.setCurrentItem(item)
        current = self.item_list.currentItem()
        if current is None or current.data(Qt.ItemDataRole.UserRole) != item_id:
            return
        menu = QMenu(self.item_list)
        menu.addActions(list(self._action_buttons))
        try:
            menu.exec(self.item_list.viewport().mapToGlobal(position))
        finally:
            menu.deleteLater()

    def set_reorder_enabled(self, enabled: bool) -> None:
        mode = QAbstractItemView.DragDropMode
        self.item_list.setDragDropMode(mode.InternalMove if enabled else mode.NoDragDrop)

    def set_heading(self, text):
        self.heading.setText(text)

    def add_item(self, item_id: str, name: str) -> None:
        if item_id in self._items:
            raise ValueError(tr("目录项已存在：{0}", item_id))
        item = QListWidgetItem(name)
        item.setData(Qt.ItemDataRole.UserRole, item_id)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
        self._items[item_id] = item
        self.item_list.addItem(item)
        self.count_label.setText(str(len(self._items)))

    def clear(self) -> None:
        self.item_list.clear()
        self._items.clear()
        self.count_label.setText("0")

    def set_items(self, items: list[tuple[str, str]]) -> None:
        if self.item_list.item_ids() != [item_id for item_id, _name in items]:
            self.clear()
            for item_id, name in items:
                self.add_item(item_id, name)
        else:
            for item_id, name in items:
                self._items[item_id].setText(name)

    def select_item(self, item_id: str | None) -> None:
        blocker = QSignalBlocker(self.item_list)
        if item_id in self._items:
            self.item_list.setCurrentItem(self._items[item_id])
        else:
            self.item_list.setCurrentRow(-1)
        del blocker

    def _select_item(self, item: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if item is not None:
            self.item_selected.emit(item.data(Qt.ItemDataRole.UserRole))

    def _activate_item(self, item: QListWidgetItem) -> None:
        self.item_activated.emit(item.data(Qt.ItemDataRole.UserRole))
