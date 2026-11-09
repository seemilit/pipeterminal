"""Show cached terminal menus immediately and revalidate in a worker."""

import posixpath
from dataclasses import dataclass, field, replace
from threading import Event, Thread

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QMenu

from common.i18n import tr
from common.i18n.errors import error_message
from ..context_menu import FileMenuContext, build_remote_menu
from ..model import TransferCancelled
from ..navigation import read_path_entry
from .terminal_cache import TerminalEntryCache, cached_path_entry


@dataclass
class TerminalEntryQuery:
    context: object
    reference: object
    cwd: str | None
    key: tuple
    cancel: Event = field(default_factory=Event)


class TerminalFileMenu(QObject):
    _loaded = Signal(object, object, str)

    def __init__(self, actions, cache=None):
        super().__init__(actions)
        self.actions = actions
        self._menu = self._job = self._status = None
        self._terminal = self._reference = None
        self._pending = None
        self._allowed = None
        self._key = self._entry = None
        self._file_actions = []
        self._cache = cache if cache is not None else TerminalEntryCache()
        self._loaded.connect(self._completed, Qt.ConnectionType.QueuedConnection)
        actions.controller.busy_changed.connect(self._busy_changed)
        actions.controller.directories_changed.connect(self._cache.invalidate)

    def show(self, terminal, reference, cwd, position, menu=None, allowed=None):
        self.close()
        if menu is None:
            menu = QMenu(self.actions.workspace)
            copy = menu.addAction(tr("复制文本"))
            copy.setEnabled(terminal.has_selection())
            copy.triggered.connect(terminal.copy)
            paste = menu.addAction(tr("粘贴文本"))
            paste.triggered.connect(terminal.paste_clipboard)
        menu.addSeparator()
        self._menu, self._terminal, self._reference = menu, terminal, reference
        self._allowed = allowed or (lambda: True)
        context = self.actions._connection()
        self._cache.bind(context)
        self._key = self._cache.key(reference, cwd)
        entry = None
        if self.actions.controller.current(context) and self._allowed():
            if self._key in self._cache:
                entry = self._cache.get(self._key)
            else:
                entry = cached_path_entry(reference, cwd, self.actions.workspace.remote.cached_entries)
        if entry is not None:
            self._display_entry(entry, context)
        else:
            self._set_status(tr("正在读取文件信息…"))
        menu.aboutToHide.connect(lambda value=menu: self._hidden(value))
        menu.popup(position)
        if self._job is not None and self._job.key == self._key and self._job.context is not None and context is not None and (
            self._job.context.transport is context.transport
            and self._job.context.connection_stop is context.connection_stop and not self._job.cancel.is_set()
        ):
            self._pending = None
            return
        if self._job is not None:
            self._job.cancel.set()
        self._pending = TerminalEntryQuery(context, reference, cwd, self._key)
        self._start_query()

    def _busy_changed(self, busy):
        if busy and self._job is not None:
            job = self._job
            job.cancel.set()
            if self._menu is not None and self._key == job.key:
                self._pending = TerminalEntryQuery(job.context, job.reference, job.cwd, job.key)
        if not busy and self._pending is not None:
            QTimer.singleShot(0, self._start_query)

    def _start_query(self):
        if self._pending is None or self._menu is None or self.actions._closed or self._job is not None:
            return
        if not self._allowed():
            self._pending = None
            self._set_status(tr("当前终端无法执行文件操作"))
            return
        if not self.actions.controller.current(self._pending.context):
            self._pending = None
            self._set_status(tr("连接已改变，操作结果已丢弃"))
            return
        if self.actions.controller.busy:
            if self._entry is None:
                self._set_status(tr("等待文件操作完成…"))
            return
        self._job, self._pending = self._pending, None
        if self._entry is None:
            self._set_status(tr("正在读取文件信息…"))
        Thread(target=self._read, args=(self._job,), name="terminal-file-info", daemon=True).start()

    def _read(self, job):
        entry, error = None, ""
        try:
            entry = read_path_entry(job.context, job.cancel, job.reference, job.cwd)
        except (TransferCancelled, ConnectionAbortedError):
            error = str(tr("操作已取消"))
        except Exception as exc:
            error = error_message(exc) or type(exc).__name__
        try:
            self._loaded.emit(job, entry, error)
        except RuntimeError:
            pass

    def _completed(self, job, entry, error):
        if job is not self._job:
            return
        self._job = None
        if not self.actions._closed and not job.cancel.is_set() and self.actions.controller.current(job.context):
            if error:
                # A failed verification must not revive older page metadata.
                self._cache.put(job.key, None)
            elif not self.actions.controller.busy:
                self._cache.put(job.key, entry)
            menu = self._menu
            if menu is not None and menu.isVisible() and self._key == job.key:
                if not self._allowed():
                    self._set_status(tr("当前终端无法执行文件操作"))
                elif error:
                    self._set_status(tr("无法读取此路径：{0}", error))
                elif not self.actions.controller.busy:
                    self._display_entry(entry, job.context)
        self._start_query()

    def _clear_file_actions(self):
        for action in self._file_actions:
            self._menu.removeAction(action)
            action.deleteLater()
        self._file_actions.clear()
        self._status = self._entry = None

    def _set_status(self, text):
        if self._status is None:
            self._clear_file_actions()
            self._status = self._menu.addAction(text)
            self._status.setEnabled(False)
            self._file_actions.append(self._status)
        else:
            self._status.setText(text)

    def _display_entry(self, entry, connection):
        if entry == self._entry:
            return
        self._clear_file_actions()
        self._entry = entry
        menu = self._menu
        previous = set(menu.actions())
        context = FileMenuContext(connection, entry.path if entry.directory else posixpath.dirname(entry.path), (entry,))
        terminal = self._terminal
        reference = replace(self._reference, text=entry.path, prompt=False, output="", offset=0)
        allowed = self._allowed
        def execute(action, value):
            if not allowed() or not self.actions.controller.current(value.connection) or self.actions.controller.busy:
                return
            if action in {"open", "parent", "up"}:
                target = reference
                if action == "up":
                    target = replace(reference, text=posixpath.dirname(value.directory.rstrip("/")) or "/", context_id=None, command=None)
                terminal.pathActivated.emit(target)
            else:
                self.actions.execute(action, value, choose_download_directory=True)
        build_remote_menu(self.actions.workspace, context, execute, enabled=True,
                           can_paste=self.actions.clipboard.can_paste(connection), menu=menu)
        self._file_actions = [action for action in menu.actions() if action not in previous]

    def _hidden(self, menu):
        if self._menu is menu:
            self._menu = self._status = None
            self._terminal = self._reference = None
            self._pending = self._allowed = None
            self._key = self._entry = None
            self._file_actions.clear()
        menu.deleteLater()

    def close(self):
        if self._menu is not None:
            self._menu.close()

    def shutdown(self):
        self.close()
        self._pending = None
        if self._job is not None:
            self._job.cancel.set()
        self._cache.bind(None)
