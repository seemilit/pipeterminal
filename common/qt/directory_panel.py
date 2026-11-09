"""Directory list populated by the currently active feature."""

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from common.i18n.widgets import QLabel
from common.i18n import tr


class DirectoryPanel(QFrame):
    item_selected = Signal(str)
    item_activated = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("directoryPanel")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumWidth(140)
        self._items: dict[str, QListWidgetItem] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QWidget()
        header.setObjectName("directoryHeader")
        heading_layout = QHBoxLayout(header)
        heading_layout.setContentsMargins(14, 10, 12, 10)
        self.heading = QLabel(tr("配置列表"))
        self.heading.setObjectName("directoryHeading")
        self.count_label = QLabel("0")
        self.count_label.setObjectName("directoryCount")
        heading_layout.addWidget(self.heading, 1)
        heading_layout.addWidget(self.count_label)
        layout.addWidget(header)
        self.item_list = QListWidget()
        self.item_list.setObjectName("directoryList")
        self.item_list.setSpacing(3)
        self.item_list.currentItemChanged.connect(self._select_item)
        self.item_list.itemDoubleClicked.connect(self._activate_item)
        layout.addWidget(self.item_list, 1)

    def set_heading(self, text):
        self.heading.setText(text)

    def add_item(self, item_id: str, name: str) -> None:
        if item_id in self._items:
            raise ValueError(tr("目录项已存在：{0}", item_id))
        item = QListWidgetItem(name)
        item.setData(Qt.ItemDataRole.UserRole, item_id)
        self._items[item_id] = item
        self.item_list.addItem(item)
        self.count_label.setText(str(len(self._items)))

    def clear(self) -> None:
        self.item_list.clear()
        self._items.clear()
        self.count_label.setText("0")

    def set_items(self, items: list[tuple[str, str]]) -> None:
        current = [
            self.item_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.item_list.count())
        ]
        if current != [item_id for item_id, _name in items]:
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
