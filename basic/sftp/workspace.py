"""Independent file views with an optionally shared transfer queue."""

import posixpath
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QMessageBox, QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

from common.qt.file_dialog import choose_directory, choose_files
from common.i18n import tr
from common.i18n.widgets import (
    QDialog, QLabel, QPushButton, QTabWidget,
)

from .browser import LocalBrowser, RemoteBrowser
from .controller import TransferController
from .file_operations.controller import FileOperationController
from .file_operations.actions import RemoteFileActions
from .display_controls import TransferDisplayControls


class FileTransferWorkspace(QWidget):
    close_requested = Signal()
    command_requested = Signal(str)

    def __init__(self, parent=None, *, transfer_controller=None, file_operations=None) -> None:
        super().__init__(parent)
        self._embedded = False
        self._closed = False
        self._connected = False
        self._drag_token = uuid4().hex
        self._session = None
        self._directory_picker = None
        self._prompts = {}
        self._pending_upload_selection = None
        self._log_service = None
        layout = QVBoxLayout(self)
        self.display_controls = TransferDisplayControls(self)
        self.display_controls.hide()
        layout.addWidget(self.display_controls)
        self.target = QLabel()
        layout.addWidget(self.target)
        self.tabs = QTabWidget()
        self._normal_size_policy = self.sizePolicy()
        self._normal_tabs_policy = self.tabs.sizePolicy()
        self.files_page = QWidget()
        files_layout = QVBoxLayout(self.files_page)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.file_splitter = splitter
        self.local = LocalBrowser()
        self.remote = RemoteBrowser(with_directory_tree=True)
        self.remote.directory_tree.hide()
        self.remote.view_mode_button.hide()
        self.local.tree.files_dropped.connect(self._drop_download)
        splitter.addWidget(self.local)
        splitter.addWidget(self.remote)
        splitter.setSizes([500, 500])
        files_layout.addWidget(splitter, 1)
        self.file_actions = QWidget()
        actions = QHBoxLayout(self.file_actions)
        actions.setContentsMargins(0, 0, 0, 0)
        self.notice = QLabel(tr("选择文件或文件夹，然后上传或下载"))
        self.notice.setWordWrap(True)
        actions.addWidget(self.notice, 1)
        self.upload = QPushButton(tr("上传 →"))
        self.upload.clicked.connect(self._upload)
        self.upload_folder = QPushButton(tr("上传文件夹"))
        self.upload_folder.clicked.connect(self._upload_folder)
        self.upload_folder.hide()
        self.download = QPushButton(tr("← 下载"))
        self.download.clicked.connect(self._download)
        actions.addWidget(self.upload)
        actions.addWidget(self.upload_folder)
        actions.addWidget(self.download)
        files_layout.addWidget(self.file_actions)
        self.tabs.addTab(self.files_page, tr("文件"))
        self.controller = TransferController(self)
        self.transfer_controller = transfer_controller if transfer_controller is not None else self.controller
        self.file_operations = file_operations if file_operations is not None else FileOperationController(self)
        self._owns_file_operations = file_operations is None
        self.file_actions_handler = RemoteFileActions(self, self.file_operations)
        layout.addWidget(self.tabs, 1)
        self.footer = QWidget()
        close_row = QHBoxLayout(self.footer)
        close_row.setContentsMargins(0, 0, 0, 0)
        self.connection_status = QLabel(tr("等待连接"))
        close_row.addWidget(self.connection_status, 1)
        close = QPushButton(tr("关闭"))
        close.clicked.connect(lambda _checked=False: self.close_requested.emit())
        close_row.addWidget(close)
        layout.addWidget(self.footer)
        self.remote.directory_requested.connect(self.browse_directory)
        self.remote.tree_changed.connect(self._bind_remote_tree)
        self.remote.readiness_changed.connect(self._update_actions)
        self.remote.directory_selection_requested.connect(self._choose_remote_directory)
        self.remote.context_requested.connect(self.file_actions_handler.show_remote_menu)
        self.remote.directory_tree.context_requested.connect(lambda view, point: self.file_actions_handler.show_remote_menu(view, point, tree=True))
        self.local.context_requested.connect(self.file_actions_handler.show_local_menu)
        self.file_actions_handler.command_requested.connect(self.command_requested.emit)
        self.file_operations.directories_changed.connect(self._file_directories_changed)
        self.file_operations.busy_changed.connect(self._update_actions)
        self.controller.connection_changed.connect(self._connection_changed)
        self.controller.listing_ready.connect(self._display_directory)
        self.controller.listing_started.connect(self._listing_started)
        self.controller.listing_failed.connect(self.remote.listing_failed)
        self.controller.directory_invalidated.connect(self.remote.invalidate_directory)
        self.controller.listing_status.connect(self.remote.status.setText)
        if self.transfer_controller is self.controller:
            self.controller.overwrite_requested.connect(self._confirm_overwrite, Qt.ConnectionType.QueuedConnection)
        else:
            self.transfer_controller.directory_invalidated.connect(self._transfer_directory_invalidated)
        self.transfer_controller.upload_completed.connect(self._upload_completed)
        self.local.tree.selectionModel().selectionChanged.connect(self._update_actions)
        self._bind_remote_tree(self.remote.tree)
        self._connection_changed(False)

    def set_embedded(self, embedded: bool) -> None:
        self._embedded = embedded
        self.remote.set_compact_view(embedded)
        self.remote.directory_tree.setVisible(embedded)
        self.remote.view_mode_button.setVisible(embedded)
        self.target.setVisible(not embedded)
        self.footer.setVisible(not embedded)
        self.local.setVisible(not embedded)
        self.file_actions.setVisible(not embedded)
        self.upload_folder.setVisible(embedded)
        self.notice.setVisible(not embedded)
        if embedded:
            self.setSizePolicy(self._normal_size_policy.horizontalPolicy(), QSizePolicy.Policy.Ignored)
            self.setMinimumHeight(260)
            self.tabs.setSizePolicy(self._normal_tabs_policy.horizontalPolicy(), QSizePolicy.Policy.Ignored)
            self.tabs.setMinimumHeight(220)
        else:
            self.setSizePolicy(self._normal_size_policy)
            self.setMinimumHeight(0)
            self.tabs.setSizePolicy(self._normal_tabs_policy)
            self.tabs.setMinimumHeight(0)
            self.file_splitter.setSizes([500, 500])
        self._update_actions()

    def bind_session(self, session, name: str, directory: str | None = None, log_service=None, initial_snapshot=None) -> None:
        self._session = session
        self._log_service = log_service or self.file_operations.log_service
        self.file_operations.bind_session(session, name, log_service)
        self.target.setText(tr("服务器：{0}", name))
        if initial_snapshot is not None:
            self.remote.select_file(initial_snapshot.selected_file)
        self.remote.bind_session(session)
        self.controller.bind_session(
            session, name, directory, log_service if self.transfer_controller is self.controller else None, initial_snapshot,
        )
        self.file_actions_handler._update_cut()

    def show_directory(self, snapshot) -> None:
        self.remote.cancel_navigation()
        self._pending_upload_selection = None
        self.show_files()
        self.remote.select_file(snapshot.selected_file)
        self.controller.use_snapshot(snapshot)

    def disconnect_session(self) -> None:
        self._session = None
        self.controller.disconnect_session()
        if self.remote.directory_tree is not None:
            self.remote.directory_tree.controller.disconnect_session()
        self.remote.path.bind_session(None)
        self.remote.path.close_popups()
        if self._directory_picker is not None:
            self._directory_picker.reject()
        self._connection_changed(False)

    def enable_directory_cache(self, cache) -> None:
        self.remote.enable_page_cache(cache)

    def browse_directory(self, directory: str) -> None:
        if not self._connected:
            return
        if self._pending_upload_selection is not None:
            requested = self._pending_upload_selection[0]
            if self.remote.canonical_directory(requested) != self.remote.canonical_directory(directory):
                self._pending_upload_selection = None
        self.remote.prepare_directory(directory)
        self.controller.browse(directory)

    def locate_upload(self, task) -> None:
        if not self._connected or task.direction != "upload" or not self.transfer_controller.is_current_task(task):
            return
        directory = task.remote_directory or task.destination
        self._pending_upload_selection = None
        self.show_files()
        self.browse_directory(directory)
        if task.state == "completed" and task.uploaded_paths:
            self._pending_upload_selection = (directory, task.uploaded_paths)

    def _upload_completed(self, task) -> None:
        if self._closed or not self._connected or not task.uploaded_paths or not self.transfer_controller.is_current_task(task):
            return
        current = self.controller.requested_directory or self.remote.directory
        if self.remote.canonical_directory(current) != posixpath.normpath(task.remote_directory):
            return
        paths = task.uploaded_paths
        if self._pending_upload_selection is not None:
            requested, previous = self._pending_upload_selection
            if self.remote.canonical_directory(requested) == posixpath.normpath(task.remote_directory):
                paths = tuple(dict.fromkeys((*previous, *paths)))
        # The controller has already started the fresh listing. Stage selection
        # afterward so listing_started cannot discard it.
        self._pending_upload_selection = (current, paths)

    def _bind_remote_tree(self, tree) -> None:
        self.file_actions_handler.bind_clipboard_shortcuts(tree)
        self.local.tree.configure_transfer(tree, self.local.selected_paths, self.local.drop_directory)
        tree.configure_transfer(self.local.tree, self.remote.selected_paths, self.remote.drop_directory,
                                self.file_actions_handler._connection)
        folders = self.remote.directory_tree
        if folders is not None:
            folders.tree.configure_transfer(tree, folders.selected_paths, folders.drop_directory,
                                            self.file_actions_handler._connection)
            if not getattr(folders.tree, "_workspace_bound", False):
                folders.tree._workspace_bound = True
                folders.tree.files_dropped.connect(self._drop_upload)
        if not getattr(tree, "_workspace_bound", False):
            tree._workspace_bound = True
            tree.files_dropped.connect(self._drop_upload)
            tree.itemSelectionChanged.connect(self._update_actions)
        self._update_actions()

    def update_profile(self, name: str, directory: str | None) -> None:
        self.target.setText(tr("服务器：{0}", name))
        self.controller.update_profile(name, directory)

    def show_files(self) -> None:
        self.tabs.setCurrentWidget(self.files_page)

    def _connection_changed(self, connected: bool) -> None:
        self._pending_upload_selection = None
        self._connected = connected
        self._drag_token = uuid4().hex
        self.remote.set_connected(connected)
        self.connection_status.setText(tr("已连接") if connected else tr("等待连接"))
        self.file_actions_handler._update_cut()
        self._update_actions()

    def _update_actions(self, *_args) -> None:
        ready = self._connected and self.remote.ready and not self.file_operations.busy
        self.upload.setEnabled(ready and (self._embedded or bool(self.local.selected_paths())))
        self.upload_folder.setEnabled(ready and self._embedded)
        self.download.setEnabled(ready and bool(self.remote.selected_paths()))
        self.local.tree.set_transfer_state(ready and not self._embedded, self._drag_token)
        self.remote.tree.set_transfer_state(ready, self._drag_token)
        if self.remote.directory_tree is not None:
            self.remote.directory_tree.tree.set_transfer_state(ready, self._drag_token)

    def _listing_started(self) -> None:
        self.remote.begin_listing()
        self._update_actions()

    def _display_directory(self, directory, entries) -> None:
        self.remote.record_directory_alias(self.controller.requested_directory, directory)
        self.remote.display_directory(directory, entries, partial=self.controller.partial_listing)
        pending, self._pending_upload_selection = self._pending_upload_selection, None
        if pending is not None and self.remote.canonical_directory(pending[0]) == posixpath.normpath(directory):
            self.remote.select_files(pending[1])
        self._update_actions()

    def _file_directories_changed(self, directories) -> None:
        if self._closed:
            return
        current = self.controller.requested_directory or self.remote.directory
        canonical = self.remote.canonical_directory(current)
        affected = tuple(self.remote.canonical_directory(path) for path in directories)
        refresh = any(canonical == path or canonical.startswith(path.rstrip("/") + "/") for path in affected)
        for path in affected:
            self.remote.invalidate_directory(path)
        if refresh and self._connected:
            self.browse_directory(current)

    def select_operation_results(self, paths) -> None:
        if not self._connected or not paths:
            return
        current = self.controller.requested_directory or self.remote.directory
        directory = self.remote.canonical_directory(current)
        selected = tuple(path for path in paths if posixpath.dirname(path) == directory)
        if selected:
            if self.controller.is_listing:
                self._pending_upload_selection = (current, selected)
            else:
                self.remote.select_files(selected)

    def can_close(self):
        return self.file_actions_handler.close_editors()

    def _transfer_directory_invalidated(self, directory: str) -> None:
        if self._closed:
            return
        self.remote.invalidate_directory(directory)
        if self._connected:
            self.browse_directory(self.controller.requested_directory or self.remote.directory)

    def _choose_remote_directory(self) -> None:
        if not self._connected or self._session is None:
            return
        from .directory_picker import RemoteDirectoryDialog

        picker = RemoteDirectoryDialog(self._session, self.controller.directory, self)
        self._directory_picker = picker
        try:
            if picker.exec() == QDialog.DialogCode.Accepted and self._connected and picker.directory is not None:
                self.remote.request_directory(picker.directory)
        finally:
            self._directory_picker = None
            picker.deleteLater()

    def _upload(self) -> None:
        if self._embedded:
            sources, _filter = choose_files(self, tr("上传"), self.local.directory)
            if sources:
                self.local.open_directory(str(Path(sources[0]).parent))
        else:
            sources = self.local.selected_paths()
        self._queue_transfer("upload", sources, self.remote.directory)

    def _upload_folder(self) -> None:
        directory = choose_directory(self, tr("选择目录"), self.local.directory)
        if directory:
            self.local.open_directory(str(Path(directory).parent))
            self._queue_transfer("upload", [directory], self.remote.directory)

    def _download(self) -> None:
        sources = self.remote.selected_paths()
        if self._embedded:
            directory = choose_directory(self, tr("选择目录"), self.local.directory)
            if not directory:
                return
            self.local.open_directory(directory)
        self._queue_transfer("download", sources, self.local.directory)

    def _drop_upload(self, payload, directory: str) -> None:
        self._queue_transfer("upload", list(payload.paths), directory, source_context=payload.context)

    def _drop_download(self, payload, directory: str) -> None:
        self._queue_transfer("download", list(payload.paths), directory, source_context=payload.context)

    def _queue_transfer(self, direction: str, sources: list[str], directory: str, *, source_context=None) -> None:
        if not self._connected or not self.remote.ready or not sources or self.file_operations.busy:
            return
        self.transfer_controller.submit(direction, sources, directory, source_context=source_context)

    def _confirm_overwrite(self, request) -> None:
        if request.completed.is_set() or request.task.cancel.is_set() or request.task.context.connection_stop.is_set():
            request.completed.set()
            return
        box = QMessageBox(
            QMessageBox.Icon.Question, tr("覆盖文件"),
            tr("目标文件已存在，是否覆盖？\n{0}\n\n选择“否”跳过此文件，选择“取消”停止本次任务。", request.path),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            self,
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)
        self._prompts[id(request)] = box

        def completed(result):
            request.answer = (
                "overwrite" if result == QMessageBox.StandardButton.Yes
                else "skip" if result == QMessageBox.StandardButton.No else "cancel"
            )
            request.completed.set()
            self._prompts.pop(id(request), None)
            box.deleteLater()

        box.finished.connect(completed)
        timer = QTimer(box)
        timer.setInterval(100)
        timer.timeout.connect(lambda: box.reject() if request.completed.is_set() or request.task.cancel.is_set() or request.task.context.connection_stop.is_set() else None)
        timer.start()
        box.open()

    def shutdown(self) -> None:
        self._closed = True
        self.file_actions_handler.shutdown()
        if self._owns_file_operations:
            self.file_operations.shutdown()
        self._connection_changed(False)
        if self._directory_picker is not None:
            self._directory_picker.reject()
        self.controller.detach_log()
        self.controller.shutdown()
        self.local.shutdown()
        self.remote.shutdown()
        for box in list(self._prompts.values()):
            box.reject()
        self.close()
