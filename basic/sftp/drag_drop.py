"""Copy-only file drags across connected workspaces and windows."""

import json
from dataclasses import dataclass

from PySide6.QtCore import QMimeData, Qt, QUrl, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QAbstractItemView, QTreeView
from shiboken6 import isValid

from common.i18n.widgets import QTreeWidget


LOCAL_FILES_MIME = "application/x-pipeterminal-local-files"
REMOTE_FILES_MIME = "application/x-pipeterminal-remote-files"


@dataclass(frozen=True)
class FileDrop:
    paths: tuple[str, ...]
    context: object = None


class _TransferDrag:
    def __init__(self, view, mime_type: str) -> None:
        self.view = view
        self.mime_type = mime_type
        self.peer = None
        self.paths = None
        self.destination = None
        self.token = ""
        self.enabled = False
        self.context = None
        self._active = None
        view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        view.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        view.setDefaultDropAction(Qt.DropAction.CopyAction)
        view.setDropIndicatorShown(False)
        self.set_state(False, "")

    def configure(self, peer, paths, destination, context=None) -> None:
        self.peer, self.paths, self.destination = peer, paths, destination
        self.context = context

    def set_state(self, enabled: bool, token: str) -> None:
        self.enabled = enabled and self.peer is not None
        self.token = token
        self.view.setDragEnabled(self.enabled)
        self.view.setAcceptDrops(self.enabled)
        self.view.viewport().setAcceptDrops(self.enabled)

    def start(self) -> None:
        if not self.enabled or self.paths is None:
            return
        paths = self.paths()
        if not paths:
            return
        context = self.context() if self.context is not None else None
        if self.mime_type == REMOTE_FILES_MIME and context is None:
            return
        self._active = FileDrop(tuple(paths), context)
        mime = QMimeData()
        mime.setData(self.mime_type, json.dumps({
            "token": self.token, "paths": paths,
        }, ensure_ascii=False).encode("utf-8"))
        if self.mime_type == LOCAL_FILES_MIME:
            mime.setUrls([QUrl.fromLocalFile(path) for path in paths])
        drag = QDrag(self.view)
        drag.setMimeData(mime)
        try:
            drag.exec(Qt.DropAction.CopyAction)
        finally:
            self._active = None
            if isValid(drag):
                drag.deleteLater()

    def _read_payload(self, event):
        source = getattr(event.source(), "_transfer_drag", None)
        if (
            not self.enabled or not isinstance(source, _TransferDrag) or source is self
            or not source.enabled or source._active is None
            or not event.possibleActions() & Qt.DropAction.CopyAction
            or self.mime_type == source.mime_type == LOCAL_FILES_MIME
        ):
            return None
        mime_type = source.mime_type
        if not event.mimeData().hasFormat(mime_type):
            return None
        try:
            payload = json.loads(bytes(event.mimeData().data(mime_type)).decode("utf-8"))
        except (ValueError, UnicodeError):
            return None
        if not isinstance(payload, dict) or payload.get("token") != source.token:
            return None
        paths = payload.get("paths")
        if not isinstance(paths, list) or not all(isinstance(path, str) and path for path in paths):
            return None
        active = source._active
        if tuple(paths) != active.paths:
            return None
        if active.context is not None:
            current = source.context() if source.context is not None else None
            if (current is None or current.transport is not active.context.transport
                    or current.connection_stop is not active.context.connection_stop
                    or active.context.connection_stop.is_set() or not active.context.transport.is_active()):
                return None
        return active

    def accept(self, event) -> None:
        if self._read_payload(event) is not None:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def drop(self, event) -> None:
        payload = self._read_payload(event)
        if payload is not None and self.destination is not None:
            directory = self.destination(event.position().toPoint())
            if directory:
                event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()
                # Never call the filesystem model's dropMimeData or move rows.
                self.view.files_dropped.emit(payload, directory)
                return
        event.ignore()


class LocalTransferTree(QTreeView):
    files_dropped = Signal(object, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._transfer_drag = _TransferDrag(self, LOCAL_FILES_MIME)

    def configure_transfer(self, peer, paths, destination, context=None) -> None:
        self._transfer_drag.configure(peer, paths, destination, context)

    def set_transfer_state(self, enabled: bool, token: str) -> None:
        self._transfer_drag.set_state(enabled, token)

    def startDrag(self, _supported_actions) -> None:
        self._transfer_drag.start()

    def dragEnterEvent(self, event) -> None:
        self._transfer_drag.accept(event)

    def dragMoveEvent(self, event) -> None:
        self._transfer_drag.accept(event)

    def dropEvent(self, event) -> None:
        self._transfer_drag.drop(event)


class RemoteTransferTree(QTreeWidget):
    files_dropped = Signal(object, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._transfer_drag = _TransferDrag(self, REMOTE_FILES_MIME)

    def configure_transfer(self, peer, paths, destination, context=None) -> None:
        self._transfer_drag.configure(peer, paths, destination, context)

    def set_transfer_state(self, enabled: bool, token: str) -> None:
        self._transfer_drag.set_state(enabled, token)

    def startDrag(self, _supported_actions) -> None:
        self._transfer_drag.start()

    def dragEnterEvent(self, event) -> None:
        self._transfer_drag.accept(event)

    def dragMoveEvent(self, event) -> None:
        self._transfer_drag.accept(event)

    def dropEvent(self, event) -> None:
        self._transfer_drag.drop(event)
