"""Record uncaught Python errors before the application loads Qt."""

import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path


crash_log_path: Path | None = None


def install_crash_logging(entry_file: str) -> None:
    global crash_log_path
    root = Path(sys.executable if getattr(sys, "frozen", False) else entry_file).resolve().parent
    log_path = crash_log_path = root / "logs" / "error.log"
    lock = threading.Lock()
    previous_hook = sys.excepthook
    previous_thread_hook = threading.excepthook

    def write_error(exc_type, exc_value, exc_traceback, source: str) -> None:
        if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            return
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        details = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        try:
            with lock:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                with log_path.open("a", encoding="utf-8", errors="backslashreplace") as stream:
                    stream.write(f"\n[{timestamp}] {source}\n{details}")
        except OSError:
            # The original exception handler still reports the error if the log is unwritable.
            pass

    def handle_error(exc_type, exc_value, exc_traceback) -> None:
        write_error(exc_type, exc_value, exc_traceback, "Application")
        previous_hook(exc_type, exc_value, exc_traceback)

    def handle_thread_error(args) -> None:
        name = args.thread.name if args.thread is not None else "unknown"
        write_error(args.exc_type, args.exc_value, args.exc_traceback, f"Thread: {name}")
        previous_thread_hook(args)

    sys.excepthook = handle_error
    threading.excepthook = handle_thread_error
