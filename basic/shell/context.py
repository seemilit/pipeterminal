"""An immutable reference to one authenticated connection, without credentials."""

from dataclasses import dataclass
from threading import Event
from typing import Any


@dataclass(frozen=True)
class SSHConnectionContext:
    transport: Any
    connection_stop: Event
