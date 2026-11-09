"""Read metadata only for the current hover; never create a file-browser page."""

from threading import Thread

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from ..navigation import read_path_entry
from .terminal_cache import TerminalEntryCache
from .terminal_menu import TerminalEntryQuery


class TerminalEntryPrefetch(QObject):
    _loaded = Signal(object, object)

    def __init__(self, connection, parent=None):
        super().__init__(parent)
        self.connection = connection
        self.cache = TerminalEntryCache()
        self._active = self._pending = None
        self._closed = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._start)
        self._loaded.connect(self._completed, Qt.ConnectionType.QueuedConnection)

    def hover(self, reference, cwd):
        self._timer.stop()
        self._pending = None
        context = self.connection()
        self.cache.bind(context)
        if self._active is not None:
            self._active.cancel.set()
        if self._closed or reference is None or context is None:
            return
        key = self.cache.key(reference, cwd)
        if self.cache.is_fresh(key):
            return
        self._pending = TerminalEntryQuery(context, reference, cwd, key)
        self._timer.start()

    def _start(self):
        if self._closed or self._active is not None or self._pending is None:
            return
        self._active, self._pending = self._pending, None
        Thread(target=self._read, args=(self._active,), name="terminal-hover-info", daemon=True).start()

    def _read(self, job):
        entry = None
        try:
            entry = read_path_entry(job.context, job.cancel, job.reference, job.cwd)
        except Exception:
            pass
        try:
            self._loaded.emit(job, entry)
        except RuntimeError:
            pass

    def _completed(self, job, entry):
        if job is not self._active:
            return
        self._active = None
        context = self.connection()
        if not self._closed and not job.cancel.is_set() and context is not None and (
            context.transport is job.context.transport and context.connection_stop is job.context.connection_stop
            and not context.connection_stop.is_set()
        ):
            self.cache.put(job.key, entry)
        if self._pending is not None:
            self._timer.start()

    def reset(self, *_args):
        self._timer.stop()
        self._pending = None
        if self._active is not None:
            self._active.cancel.set()
        self.cache.bind(None)

    def shutdown(self):
        self._closed = True
        self.reset()
