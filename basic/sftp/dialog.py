"""Standalone and in-window hosts sharing the same transfer view."""

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QVBoxLayout

from common.i18n import tr
from common.i18n.errors import error_message
from common.i18n.widgets import QDialog

from .preferences import FileViewPreferences
from .workspace import FileTransferWorkspace


class FileTransferDialog(QDialog):
    panel_state_changed = Signal(bool)
    bottom_panel_requested = Signal(str, object, object)
    bottom_panel_removed = Signal(str)
    panel_focus_requested = Signal(object, bool)
    view_closed = Signal()
    new_view_requested = Signal()
    new_panel_requested = Signal()

    def __init__(self, parent=None, *, transfer_controller=None, file_operations=None, allow_mode_switch=False) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("文件传输"))
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMinMaxButtonsHint)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setMinimumSize(760, 440)
        self.resize(1040, 640)
        self._embedded = False
        self._window_mode = False
        self._panel = None
        self._display_preferences = FileViewPreferences() if allow_mode_switch else None
        self._maximized_before_fullscreen = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.workspace = FileTransferWorkspace(self, transfer_controller=transfer_controller, file_operations=file_operations)
        self.workspace.close_requested.connect(self._close_requested)
        self.workspace.display_controls.setVisible(allow_mode_switch)
        if self._display_preferences is not None:
            self.workspace.display_controls.set_mode(self._display_preferences.read_display_mode())
        self.workspace.display_controls.mode_requested.connect(self.set_display_mode)
        self.workspace.display_controls.fullscreen_requested.connect(self._toggle_fullscreen)
        layout.addWidget(self.workspace)
        self.finished.connect(lambda _result: self.view_closed.emit())

    def create_popup(self, parent=None):
        return FileTransferDialog(parent, transfer_controller=self.workspace.transfer_controller,
                                  file_operations=self.workspace.file_operations, allow_mode_switch=True)

    def _close_requested(self):
        if self._window_mode and self._panel is not None:
            self._panel.close_requested.emit()
        else:
            self.close()

    def set_display_mode(self, mode):
        if mode == "window":
            self.show_panel()
        elif mode == "standalone":
            self.show_files()
        else:
            return
        if self._display_preferences is not None:
            try:
                self._display_preferences.save_display_mode(mode)
            except (OSError, ValueError) as exc:
                self.workspace.remote.status.setText(tr("保存显示方式失败：{0}", error_message(exc)))

    def show_panel(self):
        if self._panel is None:
            from .panel import FileTransferPanel

            self._panel = FileTransferPanel(self)
            self._panel.bottom_panel_removed.connect(self.bottom_panel_removed.emit)
            self._panel.panel_focus_requested.connect(self.panel_focus_requested.emit)
        self._panel.attach()
        self.bottom_panel_requested.emit(self._panel.panel_id, self._panel.windowTitle(), self._panel)

    def open_transfer(self):
        mode = (
            self._display_preferences.read_display_mode() if self._display_preferences is not None
            else "window" if self._window_mode else "standalone"
        )
        self.show_panel() if mode == "window" else self.show_files()

    def _toggle_fullscreen(self):
        if self._window_mode:
            return
        if self.isFullScreen():
            self.showMaximized() if self._maximized_before_fullscreen else self.showNormal()
        else:
            self._maximized_before_fullscreen = self.isMaximized()
            self.showFullScreen()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self._toggle_fullscreen()
            event.accept()
            return
        super().keyPressEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "workspace"):
            self.workspace.display_controls.set_fullscreen(self.isFullScreen())

    def can_close(self):
        return self.workspace.can_close()

    def closeEvent(self, event):
        if not self.workspace._closed and not self.can_close():
            event.ignore()
            return
        super().closeEvent(event)

    def create_tasks_dialog(self, parent=None, *, anchor=None):
        from .task_dialog import TransferTasksDialog

        return TransferTasksDialog(self.workspace.transfer_controller, parent, anchor=anchor)

    def bind_session(self, session, name: str, directory: str | None = None, log_service=None, initial_snapshot=None, *, server_address: str = "") -> None:
        self.workspace.bind_session(session, name, directory, log_service, initial_snapshot)
        self._update_server_display(name, server_address)

    def show_directory(self, snapshot) -> None:
        self.workspace.show_directory(snapshot)

    def update_profile(self, name: str, directory: str | None, *, server_address: str = "") -> None:
        self.workspace.update_profile(name, directory)
        self._update_server_display(name, server_address)

    def _update_server_display(self, name: str, server_address: str) -> None:
        self.setWindowTitle(f"{name} SFTP" if name else tr("文件传输"))
        self.workspace.target.setText(tr("服务器：{0}", f"{name} ({server_address})" if server_address else name))

    def _attach_workspace(self) -> None:
        if self._window_mode:
            self.workspace.setParent(self)
            self.layout().addWidget(self.workspace)
            self._window_mode = False
        if self._embedded:
            self.panel_state_changed.emit(False)
            self.layout().addWidget(self.workspace)
            self._embedded = False
        self.workspace.set_embedded(False)
        self.workspace.display_controls.set_mode("standalone")
        self.workspace.show()

    def embed_transfer(self, parent):
        if self.isFullScreen():
            self.showNormal()
        self.hide()
        if self.workspace.parentWidget() is not parent:
            self.workspace.setParent(parent)
        self._window_mode = True
        self.workspace.set_embedded(False)
        self.workspace.display_controls.set_mode("window")
        self.workspace.show_files()
        self.workspace.show()
        return self.workspace

    def show_files(self) -> None:
        if self._window_mode and self._panel is not None:
            self.bottom_panel_removed.emit(self._panel.panel_id)
        self._attach_workspace()
        self.workspace.show_files()
        self.show()
        self.raise_()
        self.activateWindow()

    def embed_files(self, parent):
        self.hide()
        self.workspace.setParent(parent)
        self._embedded = True
        self.workspace.set_embedded(True)
        self.workspace.show_files()
        self.workspace.show()
        self.panel_state_changed.emit(True)
        return self.workspace

    def hide_embedded(self) -> None:
        if self._embedded:
            self.workspace.hide()
            self.panel_state_changed.emit(False)

    def shutdown(self) -> None:
        if self._panel is not None:
            self.bottom_panel_removed.emit(self._panel.panel_id)
        self.workspace.shutdown()
        if self._panel is not None:
            self._panel.deleteLater()
            self._panel = None
        self.panel_state_changed.emit(False)
        self.close()
