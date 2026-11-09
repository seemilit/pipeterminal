"""Transfer records shared with workers; cancellation uses threading events."""

from dataclasses import dataclass, field
from threading import Event
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class RemoteEntry:
    name: str
    path: str
    directory: bool
    link: bool
    size: int
    modified: int
    mode: int = 0


@dataclass(frozen=True)
class PlannedEntry:
    source: str
    target: str
    size: int
    directory: bool = False


@dataclass
class TransferTask:
    direction: str
    sources: tuple[str, ...]
    destination: str
    context: Any
    id: str = field(default_factory=lambda: uuid4().hex)
    cancel: Event = field(default_factory=Event)
    state: str = "waiting"
    current: int = 0
    total: int = 0
    filename: str = ""
    detail: str = ""
    remote_directory: str = ""
    remote_targets: tuple[str, ...] = ()
    uploaded_paths: tuple[str, ...] = ()
    source_context: Any = None
    transfer_handler: Any = None
    file_handler: Any = None
    resume_identity: Any = None


@dataclass
class OverwriteRequest:
    task: TransferTask
    path: str
    completed: Event = field(default_factory=Event)
    answer: str = "cancel"


class TransferCancelled(Exception):
    pass


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
