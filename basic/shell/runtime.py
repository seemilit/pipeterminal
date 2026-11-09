"""Per-connection worker state, bounded queues and host-key decisions."""

from dataclasses import dataclass, field
from queue import Queue
from threading import Event, Lock
from typing import Any
from uuid import uuid4


@dataclass
class HostKeyRequest:
    hostname: str
    key_type: str
    fingerprint: str
    cancelled: Event
    completed: Event = field(default_factory=Event)
    accepted: bool = False


@dataclass
class ConnectionRun:
    shell_token: str = field(default_factory=lambda: uuid4().hex)
    command_names: tuple[str, ...] = ()
    prompt_extension: Any = None
    stop: Event = field(default_factory=Event)
    incoming: Queue = field(default_factory=lambda: Queue(maxsize=64))
    outgoing: Queue = field(default_factory=lambda: Queue(maxsize=256))
    notification_lock: Lock = field(default_factory=Lock)
    notified: bool = False
    channel: Any = None
    client: Any = None
    owns_channel: bool = True
    size: tuple[int, int] = (80, 24)
    applied_size: tuple[int, int] | None = None
    done: bool = False
    error: str = ""
    output_observer: Any = None
