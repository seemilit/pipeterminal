"""Background UTF-8 logging with incremental terminal-control filtering."""

from datetime import datetime
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread

from .filter import OutputFilter

from common.i18n import tr

from common.i18n.errors import error_message


class LogWriter:
    def __init__(self, path: Path, *, error_callback=None) -> None:
        self.path = path
        self.error: str | None = None
        self._error_callback = error_callback
        self.closed = Event()
        self._closing = Event()
        self._enqueue_lock = Lock()
        self._queue = Queue(maxsize=256)
        self._handle = None
        self._partial: list[str] = []
        self._cr = False
        self._line_start = True
        self._parser = OutputFilter(self)
        self._thread = Thread(target=self._run, name="session-log-writer", daemon=True)
        self._thread.start()

    def output(self, data: bytes) -> bool:
        """Called by the SSH reader, allowing backpressure without blocking Qt."""
        while True:
            with self._enqueue_lock:
                if self._closing.is_set() or self.closed.is_set():
                    return False
                try:
                    self._queue.put_nowait(("output", data))
                    return True
                except Full:
                    pass
            self._closing.wait(0.05)

    def event(self, kind: str, message: str) -> bool:
        with self._enqueue_lock:
            if self._closing.is_set() or self.closed.is_set():
                return False
            try:
                self._queue.put_nowait((kind, message))
                return True
            except Full:
                pass
        self._report_error(tr("日志队列已满，无法记录状态事件"))
        return False

    def close(self) -> None:
        with self._enqueue_lock:
            self._closing.set()

    def _report_error(self, message: str) -> None:
        self.error = message
        if self._error_callback is not None:
            try:
                self._error_callback(self.path, message)
            except RuntimeError:
                pass

    def wait(self, timeout: float = 3.0) -> bool:
        return self.closed.wait(timeout)

    def _run(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("x", encoding="utf-8") as handle:
                self._handle = handle
                while not self._closing.is_set() or not self._queue.empty():
                    try:
                        kind, value = self._queue.get(timeout=0.05)
                    except Empty:
                        handle.flush()
                        continue
                    if kind == "output":
                        self._parser.feed(value)
                        self._flush_line()
                    else:
                        self._flush_line()
                        if not self._line_start:
                            handle.write("\n")
                            self._line_start = True
                        self._write_line(f"[{kind}] {value}")
                    handle.flush()
                self._parser.feed(b"", final=True)
                self._flush_line()
                handle.flush()
        except (OSError, ValueError) as exc:
            self._report_error(error_message(exc))
        finally:
            self._handle = None
            self.closed.set()

    def _write_line(self, value: str) -> None:
        if self._handle is not None:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            self._handle.write(f"[{timestamp}] {value}\n")
            self._line_start = True

    def _flush_line(self) -> None:
        if self._partial:
            value = "".join(self._partial)
            for part in value.splitlines(keepends=True):
                if self._line_start and part != "\n":
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                    self._handle.write(f"[{timestamp}] ")
                self._handle.write(part)
                self._line_start = part.endswith("\n")
            self._partial.clear()

    def draw(self, char: str) -> None:
        self._cr = False
        self._partial.append(char)
        if len(self._partial) >= 8192:
            self._flush_line()

    def control(self, char: str) -> None:
        if char == "\r":
            self._partial.append("\n")
            self._cr = True
        elif char == "\n":
            if not self._cr:
                self._partial.append("\n")
            self._cr = False
        elif char == "\t":
            self._partial.append("\t")
        elif char == "\b" and self._partial:
            self._partial.pop()
