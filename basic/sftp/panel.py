"""File-transfer page registered beside other application panels."""

from uuid import uuid4

from PySide6.QtWidgets import QVBoxLayout

from common.qt.module_page import ModulePage


class FileTransferPanel(ModulePage):
    def __init__(self, dialog):
        super().__init__()
        self.panel_id = "sftp.transfer." + uuid4().hex
        self._dialog = dialog
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setWindowTitle(dialog.windowTitle())
        dialog.windowTitleChanged.connect(self.setWindowTitle)
        self.close_requested.connect(self._request_close)
        self.new_panel_requested.connect(dialog.new_panel_requested.emit)
        self.duplicate_panel_requested.connect(dialog.new_view_requested.emit)

    def attach(self):
        workspace = self._dialog.embed_transfer(self)
        if self.layout().indexOf(workspace) < 0:
            self.layout().addWidget(workspace)

    def _request_close(self):
        if self.can_close():
            self.bottom_panel_removed.emit(self.panel_id)
            self._dialog.view_closed.emit()

    def can_close(self):
        return self._dialog.can_close()

    def can_duplicate_panel(self) -> bool:
        return not self._dialog.workspace._closed

    def can_disconnect_panel(self) -> bool:
        return self._dialog.workspace._connected

    def disconnect_panel(self) -> None:
        if self.can_close():
            self._dialog.workspace.disconnect_session()
