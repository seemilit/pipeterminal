"""Saved server selection for opening an independent Shell tab."""

from PySide6.QtWidgets import QHBoxLayout, QListWidget, QVBoxLayout

from common.i18n import tr
from common.i18n.widgets import QDialog, QPushButton


class ServerPickerDialog(QDialog):
    def __init__(self, names, current=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("选择服务器"))
        self.resize(420, 360)
        layout = QVBoxLayout(self)
        self.servers = QListWidget()
        self.servers.addItems(names)
        self.servers.setCurrentRow(names.index(current) if current in names else 0)
        self.servers.itemDoubleClicked.connect(lambda _item: self.accept())
        layout.addWidget(self.servers, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        connect_button = QPushButton(tr("连接"))
        connect_button.setDefault(True)
        connect_button.setEnabled(bool(names))
        connect_button.clicked.connect(self.accept)
        row.addWidget(connect_button)
        cancel_button = QPushButton(tr("取消"))
        cancel_button.clicked.connect(self.reject)
        row.addWidget(cancel_button)
        layout.addLayout(row)

    def selected_name(self):
        item = self.servers.currentItem()
        return item.text() if item is not None else None
