"""File clipboard shared across local views and SSH connections."""

from dataclasses import dataclass
from uuid import uuid4

from PySide6.QtCore import QMimeData, QObject, QUrl, Signal
from PySide6.QtWidgets import QApplication

MIME = "application/x-pipeterminal-remote-clipboard"


@dataclass
class RemoteClipboardData:
    context: object
    paths: tuple[str, ...]
    cut: bool
    token: str
    in_flight: bool = False


class RemoteClipboard(QObject):
    changed = Signal()
    status = Signal(object)

    def __init__(self) -> None:
        super().__init__(QApplication.instance())
        self.value = None
        self._registry = None
        QApplication.clipboard().dataChanged.connect(self._clipboard_changed)

    def bind_registry(self, registry):
        self._registry = registry

    @property
    def provider(self):
        return self._registry.get_service("sftp_file_bridge") if self._registry is not None else None

    def set(self, context, paths, cut):
        provider = self.provider
        if provider is not None:
            provider.cancel_export()
        self.value = RemoteClipboardData(context, tuple(dict.fromkeys(paths)), cut, uuid4().hex)
        self._publish(self.value)
        if provider is not None:
            provider.copy_remote(self, self.value)

    def _publish(self, value, local_paths=()):
        mime = QMimeData()
        mime.setData(MIME, value.token.encode("ascii"))
        mime.setText("\n".join(value.paths))
        if local_paths:
            mime.setUrls([QUrl.fromLocalFile(path) for path in local_paths])
        QApplication.clipboard().setMimeData(mime)

    def _owns_clipboard(self, value):
        mime = QApplication.clipboard().mimeData()
        return value is not None and mime is not None and bytes(mime.data(MIME)) == value.token.encode("ascii")

    def _clipboard_changed(self):
        provider = self.provider
        if not self._owns_clipboard(self.value) and provider is not None:
            provider.cancel_export()
        self.changed.emit()

    def set_local(self, paths):
        if not paths:
            return
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(path) for path in paths])
        QApplication.clipboard().setMimeData(mime)

    def local_paths(self):
        mime = QApplication.clipboard().mimeData()
        if mime is None or mime.hasFormat(MIME):
            return ()
        return tuple(dict.fromkeys(url.toLocalFile() for url in mime.urls() if url.isLocalFile()))

    def can_paste(self, context):
        if self.get(context) is not None:
            return True
        provider = self.provider
        if provider is not None:
            return provider.can_paste(self, context)
        return context is not None and (bool(self.local_paths()) or self.get(context, allow_other=True) is not None)

    def get(self, context, *, allow_other=False):
        value = self.value
        if value is None or context is None or value.in_flight or not value.paths or value.context.connection_stop.is_set() or not value.context.transport.is_active():
            return None
        same = value.context.transport is context.transport and value.context.connection_stop is context.connection_stop
        if not same and (not allow_other or value.cut):
            return None
        return value if self._owns_clipboard(value) else None

    def finish(self, value, completed=()):
        value.in_flight = False
        if value.cut:
            value.paths = tuple(path for path in value.paths if path not in completed)
        self.changed.emit()


_clipboard = None


def get_clipboard():
    global _clipboard
    if _clipboard is None:
        _clipboard = RemoteClipboard()
    return _clipboard
