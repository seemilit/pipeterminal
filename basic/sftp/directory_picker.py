"""Server folder selection with its own cancellable directory query channel."""

from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QVBoxLayout

from common.i18n import tr
from common.i18n.widgets import QDialog, QLabel, QPushButton

from .browser import RemoteBrowser
from .controller import TransferController


class RemoteDirectoryDialog(QDialog):
    def __init__(self, session, directory: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("选择目录"))
        self.resize(560, 440)
        self.directory: str | None = None
        self._connected = False
        self._directory_count = 0
        layout = QVBoxLayout(self)
        self.browser = RemoteBrowser(allow_directory_picker=False)
        self.browser.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        for column in (1, 2, 3):
            self.browser.tree.setColumnHidden(column, True)
        layout.addWidget(self.browser, 1)
        self.selected_path = QLabel()
        self.selected_path.setWordWrap(True)
        layout.addWidget(self.selected_path)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.confirm = QPushButton(tr("确定"))
        self.confirm.clicked.connect(self.accept)
        cancel = QPushButton(tr("取消"))
        cancel.clicked.connect(self.reject)
        buttons.addWidget(self.confirm)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        self.controller = TransferController(self)
        self.browser.directory_requested.connect(self.controller.browse)
        self.browser.tree.itemSelectionChanged.connect(self._update_selection)
        self.browser.readiness_changed.connect(self._update_selection)
        self.controller.connection_changed.connect(self._connection_changed)
        self.controller.listing_started.connect(self._listing_started)
        self.controller.listing_ready.connect(self._display_directory)
        self.controller.listing_failed.connect(self.browser.listing_failed)
        self.controller.listing_status.connect(self._display_status)
        self.browser.bind_session(session)
        self.controller.bind_session(session, "", None if directory == "." else directory)

    def _connection_changed(self, connected: bool) -> None:
        self._connected = connected
        self.browser.set_connected(connected)
        self._update_selection()
        if not connected and self.isVisible():
            self.reject()

    def _listing_started(self) -> None:
        self.browser.begin_listing()
        self._update_selection()

    def _display_directory(self, directory, entries) -> None:
        self.browser.record_directory_alias(self.controller.requested_directory, directory)
        folders = [entry for entry in entries if entry.directory]
        self._directory_count = len(folders)
        self.browser.display_directory(directory, folders)
        self._update_selection()

    def _display_status(self, message) -> None:
        self.browser.status.setText(
            tr("共 {0} 项", self._directory_count) if self.browser.ready else message,
        )

    def _update_selection(self) -> None:
        ready = self._connected and self.browser.ready
        selected = self.browser.selected_paths()
        self.selected_path.setText((selected[0] if selected else self.browser.directory) if ready else "")
        self.confirm.setEnabled(ready)

    def accept(self) -> None:
        if not self._connected or not self.browser.ready:
            return
        selected = self.browser.selected_paths()
        self.directory = selected[0] if selected else self.browser.directory
        self.done(QDialog.DialogCode.Accepted)

    def done(self, result: int) -> None:
        self.controller.shutdown()
        self.browser.shutdown()
        super().done(result)
