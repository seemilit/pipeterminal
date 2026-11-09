"""One background navigation worker; Qt alone activates and draws results."""

from collections import OrderedDict
from dataclasses import replace
from threading import Event, Thread

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from basic.sftp.navigation import read_path_snapshot, read_shell_directory
from basic.terminal.path_policy import ClickPathPolicy
from basic.terminal.paths import PathReference
from common.i18n import tr

from .integration import directory_input, directory_key

from common.i18n.errors import error_message


class PathNavigation(QObject):
    directory_ready = Signal(object)
    directory_changed = Signal(object)
    working_directory_changed = Signal(str)
    status_changed = Signal(str)
    _completed = Signal(object, object, str)

    def __init__(self, terminal, session, parent=None) -> None:
        super().__init__(parent)
        self.terminal, self.session = terminal, session
        self.policy = ClickPathPolicy()
        self.listing_allowed = None
        self._page_cache_manager = None
        self._epoch = 0
        self._closed = False
        self._pid = None
        self._reported_directory = None
        self._quiet_ready = False
        self._jump_snapshot = None
        self._prompt = None
        self._cwd = OrderedDict()
        self._commands = OrderedDict()
        self._current_directory = None
        self._active = self._pending = self._activation = self._hover = None
        self._cwd_job = None
        self._cancel = Event()
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(0)
        self._hover_timer.timeout.connect(self._prefetch)
        self._completed.connect(self._finish, Qt.ConnectionType.QueuedConnection)
        terminal.pathHovered.connect(self.hover)
        terminal.pathActivated.connect(self.activate)
        terminal.metadataReceived.connect(self.metadata)
        session.connected.connect(self._connected)
        session.disconnected.connect(self.reset)
        session.inputQueued.connect(self._input_queued)

    def bind_registry(self, registry) -> None:
        provider = registry.get_service("terminal_path_policy")
        self.policy.clear()
        self.policy = provider.create_policy() if provider is not None else ClickPathPolicy()

    def set_listing_allowed(self, callback) -> None:
        self.listing_allowed = callback
        self.policy.clear()
        self._hover_timer.stop()
        self._hover = None
        self.cancel_activation()
        if self._active is not None and self._active[1] == "path":
            self._cancel.set()
        if self._pending is not None and self._pending[1] == "path":
            self._pending = None

    def _connected(self) -> None:
        self.terminal.enable_path_navigation(True)
        self._start()

    @property
    def current_directory(self) -> str | None:
        return self._current_directory

    def directory_for_reference(self, reference) -> str | None:
        return self._cwd.get(reference.context_id)

    @property
    def file_actions_allowed(self) -> bool:
        return self._ready() and self._prompt is not None and self.terminal.engine.path_links_enabled

    def contextual_reference(self, reference):
        if reference is None or reference.prompt:
            return reference
        return replace(reference, command=self._commands.get(reference.context_id))

    def _set_current_directory(self, directory: str) -> None:
        if directory != self._current_directory:
            self._current_directory = directory
            self.working_directory_changed.emit(directory)

    def bind_page_cache(self, manager) -> None:
        self._page_cache_manager = manager
        manager.cache.invalidated.connect(self._invalidate_prefetch)

    def unbind_page_cache(self) -> None:
        if self._page_cache_manager is not None:
            self._page_cache_manager.cache.invalidated.disconnect(self._invalidate_prefetch)
            self._page_cache_manager = None
        self._hover_timer.stop()
        self._hover = None
        if self._activation is None and self._pending is not None and self._pending[1] == "path":
            self._pending = None
        self._invalidate_prefetch("/")

    def _invalidate_prefetch(self, _directory: str) -> None:
        self.policy.clear()
        if self._active is not None and self._active[1] == "path":
            self._cancel.set()
            hovered = self._hover is not None and self._key(self._hover) == self._active[2]
            if self._pending is None and (self._activation == self._active[2] or hovered):
                self._pending = self._active

    def _cached_snapshot(self, reference):
        key = self._key(reference)
        if self._page_cache_manager is not None:
            snapshot = self._page_cache_manager.get_snapshot(key, reference, self._cwd.get(reference.context_id))
            if snapshot is not None:
                return snapshot
        snapshot = self.policy.get(key)
        if snapshot is not None and self._page_cache_manager is not None:
            self._page_cache_manager.prepare_snapshot(key, snapshot)
        return snapshot

    def reset(self, *_args) -> None:
        self._epoch += 1
        self._cancel.set()
        self._hover_timer.stop()
        self._pending = self._activation = self._hover = self._prompt = self._pid = None
        self._cwd_job = None
        self._cwd.clear()
        self._commands.clear()
        self._current_directory = None
        self._reported_directory = None
        self._quiet_ready = False
        self._jump_snapshot = None
        self.policy.clear()
        self.terminal.enable_path_navigation(False)

    def shutdown(self) -> None:
        self._closed = True
        self.reset()

    def _input_queued(self, data: bytes) -> None:
        token = self.session.shell_token()
        if token is None or not self._quiet_ready or not data.removeprefix(b"\x15").startswith(directory_key(token)):
            self.terminal.engine.note_input(data)

    def metadata(self, kind: str, value: str) -> None:
        if self._closed:
            return
        if kind in {"command_input", "command_input_unknown"}:
            if self._prompt is not None:
                self._commands[self._prompt] = value if kind == "command_input" else ""
                self.policy.clear()
                while len(self._commands) > 5000:
                    self._commands.popitem(last=False)
            return
        if kind == "osc":
            parts = value.split(";", 3)
            if len(parts) < 3 or parts[0] != "777" or parts[2] != self.session.shell_token():
                return
            if len(parts) == 4 and parts[1] == "PipeTerminalShell":
                if parts[3].isascii() and parts[3].isdigit() and 0 < int(parts[3]) < 2 ** 31:
                    self._pid = int(parts[3])
            elif len(parts) == 4 and parts[1] == "PipeTerminalCwd":
                directory = parts[3]
                if directory.startswith("/") and not any(ord(char) < 32 or ord(char) == 127 for char in directory):
                    self._reported_directory = directory
                    self._cwd_job = None
                    if self._active is not None and self._active[1] == "cwd":
                        self._cancel.set()
                    # The server's full cwd is authoritative even if a custom
                    # prompt cannot be recognized. Associate history separately.
                    self._set_current_directory(directory)
            elif len(parts) == 3 and parts[1] == "PipeTerminalReady":
                self._quiet_ready = True
            elif len(parts) == 4 and parts[1] == "PipeTerminalJump":
                snapshot = self._jump_snapshot
                if snapshot is not None and parts[3] == snapshot.directory:
                    self._jump_snapshot = None
                    self._set_current_directory(snapshot.directory)
                    self.directory_changed.emit(snapshot)
            elif parts[1] == "PipeTerminalJumpFailed" and len(parts) == 4:
                if self._jump_snapshot is not None and parts[3] == self._jump_snapshot.directory:
                    self._jump_snapshot = None
                    self.status_changed.emit(tr("目录切换失败"))
            elif len(parts) == 3 and parts[1] in {"PipeTerminalJumpRejected", "PipeTerminalJumpFailed"}:
                self._jump_snapshot = None
                self.status_changed.emit(tr("目录切换失败"))
            return
        if kind != "prompt" or self._closed:
            return
        parts = value.split(";", 3)
        identifier, line_id = map(int, parts[:2])
        directory, self._reported_directory = self._reported_directory, None
        if len(parts) == 4:
            enabled, hint = parts[2] == "1", parts[3]
        else:
            index = self.terminal.engine.screen.index_of(line_id)
            if index is None:
                return
            line = self.terminal.engine.screen.row_at(index)
            if line.prompt_context != identifier:
                return
            enabled, hint = line.path_enabled, line.prompt_directory
        if not enabled:
            self._prompt = None
            self.cancel_activation()
            return
        if identifier == self._prompt:
            if directory is not None:
                self._remember_directory(identifier, directory)
                self._cwd_job = None
            return
        self._prompt = identifier
        if self._activation is None:
            self._pending = None
            if self._active is not None and self._active[1] == "path":
                self._cancel.set()
        if directory is not None:
            self._remember_directory(identifier, directory)
            self._cwd_job = None
        else:
            self._cwd_job = (self._epoch, "cwd", identifier, hint, self._pid)
        self._start()
        if self.policy.prefetch and self._hover is not None:
            self._hover_timer.start()

    def _remember_directory(self, identifier: int, directory: str) -> None:
        self._cwd[identifier] = directory
        while len(self._cwd) > 5000:
            self._cwd.popitem(last=False)
        if identifier == self._prompt:
            self._set_current_directory(directory)

    def send_directory(self, snapshot) -> bool:
        if not self._ready():
            return False
        token = self.session.shell_token()
        if not self._quiet_ready or token is None:
            self.status_changed.emit(tr("当前 Shell 尚未启用静默目录跳转，请重新连接"))
            return False
        self._jump_snapshot = snapshot
        if self.session.send(directory_input(token, snapshot.directory)):
            return True
        self._jump_snapshot = None
        return False

    def _key(self, reference):
        return (self._epoch, reference.context_id, reference.text, reference.prompt, reference.output, reference.offset, reference.command)

    def hover(self, reference) -> None:
        reference = self.contextual_reference(reference)
        self._hover = reference
        self._hover_timer.stop()
        if not self.policy.prefetch:
            return
        if self._active is not None and self._active[1] == "path" and self._activation is None:
            if reference is None or self._active[2] != self._key(reference):
                self._cancel.set()
        if self._pending is not None and self._pending[1] == "path" and self._activation is None:
            self._pending = None
        if reference is not None:
            self._prefetch()

    def _prefetch(self) -> None:
        reference = self._hover
        if self._activation is not None or reference is None:
            return
        if self._cached_snapshot(reference) is not None:
            return
        self._request(reference)

    def _ready(self) -> bool:
        return not self._closed and self.session.state == "connected"

    def activate(self, reference) -> None:
        if not self.file_actions_allowed:
            return
        reference = self.contextual_reference(reference)
        if not self._quiet_ready:
            self.status_changed.emit(tr("当前 Shell 尚未启用静默目录跳转，请重新连接"))
            return
        self._hover_timer.stop()
        key = self._key(reference)
        self._activation = key
        snapshot = self._cached_snapshot(reference)
        if snapshot is not None:
            self._deliver(key, snapshot)
        else:
            self.status_changed.emit(tr("正在读取目录…"))
            self._request(reference)

    def activate_entry(self, entry) -> None:
        if entry.path.startswith("/"):
            self.activate(PathReference(entry.path, None, ()))

    def cancel_activation(self, *_args) -> None:
        self._activation = None

    def _request(self, reference) -> None:
        if self._closed or self.session.state != "connected":
            return
        key = self._key(reference)
        if self._active is not None and self._active[1] == "path" and self._active[2] == key and not self._cancel.is_set():
            return
        self._pending = (
            self._epoch, "path", key, reference, self._cwd.get(reference.context_id),
        )
        if self._active is not None and self._active[1] == "path":
            self._cancel.set()
        self._start()

    def _start(self) -> None:
        if self._closed or self._active is not None or (self._pending is None and self._cwd_job is None):
            return
        context = self.session.connection_context()
        if context is None:
            return
        if self._cwd_job is not None:
            job, self._cwd_job = self._cwd_job, None
        else:
            job, self._pending = self._pending, None
        if job[1] == "path":
            job = (*job[:4], self._cwd.get(job[3].context_id))
        self._active, self._cancel = job, Event()
        Thread(target=self._work, args=(job, context, self._cancel, self.listing_allowed), name="terminal-path", daemon=True).start()

    def _work(self, job, context, cancel, listing_allowed=None) -> None:
        try:
            result = (
                read_shell_directory(context, cancel, job[4], job[3]) if job[1] == "cwd"
                else read_path_snapshot(context, cancel, job[3], job[4], listing_allowed=listing_allowed)
            )
            error = ""
        except Exception as exc:
            result, error = None, error_message(exc) or type(exc).__name__
        try:
            self._completed.emit(job, None if cancel.is_set() else result, error)
        except RuntimeError:
            pass

    def _finish(self, job, result, error: str) -> None:
        if self._active != job:
            return
        cancelled = self._cancel.is_set()
        self._active = None
        if not self._closed and job[0] == self._epoch and not cancelled:
            if job[1] == "cwd" and job[2] == self._prompt and result is not None:
                if job[2] not in self._cwd:
                    self._remember_directory(job[2], result)
            elif job[1] == "path":
                if result is not None:
                    self.policy.put(job[2], result)
                    if self._page_cache_manager is not None:
                        self._page_cache_manager.prepare_snapshot(job[2], result)
                    self._deliver(job[2], result)
                elif self._activation == job[2]:
                    self._activation = None
                    self.status_changed.emit(tr("读取目录失败：{0}", error))
        self._start()

    def _deliver(self, key, snapshot) -> None:
        if self._activation != key:
            return
        self._activation = None
        if not self._ready():
            return
        self.directory_ready.emit(snapshot)
