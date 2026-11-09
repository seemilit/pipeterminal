"""Read breadcrumb child folders in a cancellable worker."""

import time
from threading import Event, Thread

from PySide6.QtCore import QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QMenu

from common.i18n import tr
from common.i18n.errors import error_message

from .backend import list_directory
from .file_icons import RemoteFileIcons


class PathDirectoryMenu(QObject):
    path_selected = Signal(str)
    _loaded = Signal(int, object, str)

    def __init__(self, parent) -> None:
        super().__init__(parent)
        self._session = None
        self._menu = None
        self._context = None
        self._generation = 0
        self._cancel = Event()
        self._closed = False
        self._entries = None
        self._icons = RemoteFileIcons()
        self._render_timer = QTimer(self)
        self._render_timer.setInterval(10)
        self._render_timer.timeout.connect(self._render_batch)
        self._loaded.connect(self._display, Qt.ConnectionType.QueuedConnection)
        QApplication.instance().aboutToQuit.connect(self.shutdown)

    def bind_session(self, session) -> None:
        if self._session is not None:
            self._session.connected.disconnect(self.close)
            self._session.disconnected.disconnect(self.close)
        self.close()
        self._session = session
        if session is not None:
            session.connected.connect(self.close)
            session.disconnected.connect(self.close)

    def _current(self, context) -> bool:
        now = self._session.connection_context() if self._session is not None else None
        return not self._closed and context is not None and now is not None and (
            now.transport is context.transport and now.connection_stop is context.connection_stop
            and not context.connection_stop.is_set()
        )

    def show(self, directory: str, anchor) -> None:
        self.close()
        if self._closed:
            return
        menu = QMenu(self.parent())
        self._menu = menu
        self._context = self._session.connection_context() if self._session is not None else None
        status = menu.addAction(tr("正在读取目录…") if self._current(self._context) else tr("等待连接"))
        status.setEnabled(False)
        menu.aboutToHide.connect(lambda value=menu: self._hidden(value))
        menu.popup(anchor.mapToGlobal(QPoint(0, anchor.height())))
        if self._menu is menu and menu.isVisible() and self._current(self._context):
            self._cancel = Event()
            Thread(
                target=self._read, args=(self._generation, self._context, self._cancel, directory),
                name="sftp-path-menu", daemon=True,
            ).start()

    def _read(self, generation, context, cancel, directory) -> None:
        try:
            folders = self._read_folders(context, cancel, directory)
            error = ""
        except Exception as exc:
            folders, error = (), error_message(exc) or type(exc).__name__
        if not cancel.is_set():
            try:
                self._loaded.emit(generation, folders, error)
            except RuntimeError:
                pass

    def _read_folders(self, context, cancel, directory):
        _directory, entries = list_directory(context, cancel, directory)
        return tuple((entry.name, entry.path) for entry in entries if entry.directory and not entry.link)

    def _display(self, generation, folders, error) -> None:
        if generation != self._generation or self._menu is None or not self._menu.isVisible() or not self._current(self._context):
            return
        self._menu.clear()
        if error or not folders:
            action = self._menu.addAction(tr("读取目录失败：{0}", error) if error else tr("暂无子目录"))
            action.setEnabled(False)
            return
        self._entries = iter(folders)
        self._render_batch()
        if self._entries is not None:
            self._render_timer.start()

    def _render_batch(self) -> None:
        if self._entries is None or self._menu is None or not self._current(self._context):
            self._render_timer.stop()
            return
        deadline = time.monotonic() + 0.004
        for _index in range(50):
            try:
                name, path = next(self._entries)
            except StopIteration:
                self._entries = None
                self._render_timer.stop()
                return
            action = self._menu.addAction(self._icons.folder_icon(), name.replace("&", "&&"))
            action.setToolTip(path)
            action.triggered.connect(lambda _checked=False, value=path, context=self._context: self._select(value, context))
            if time.monotonic() >= deadline:
                break

    def _select(self, path, context) -> None:
        if self._current(context):
            self.path_selected.emit(path)

    def _hidden(self, menu) -> None:
        if self._menu is menu:
            self._cancel.set()
            self._render_timer.stop()
            self._entries = None
            self._menu = None
        menu.deleteLater()

    def close(self, *_args) -> None:
        self._generation += 1
        self._cancel.set()
        self._render_timer.stop()
        self._entries = None
        menu, self._menu = self._menu, None
        if menu is not None:
            menu.close()
            menu.deleteLater()

    def shutdown(self) -> None:
        self._closed = True
        self.close()
