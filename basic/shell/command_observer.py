"""Observe completed interactive commands without executing or logging them."""

import shlex
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from .integration import directory_key


@dataclass(frozen=True)
class CommandObservation:
    text: str | None
    status: int
    command_types: dict[str, tuple[str, str | None]]


class ShellCommandObserver(QObject):
    finished = Signal(object)

    def __init__(self, terminal, session, parent=None) -> None:
        super().__init__(parent)
        self.session = session
        self._closed = False
        self.reset()
        terminal.metadataReceived.connect(self.metadata)
        session.inputQueued.connect(self._input_queued)
        session.disconnected.connect(self.reset)

    def reset(self, *_args) -> None:
        self._types = {}
        self._pending_types = None
        self._active = None
        self._echo = None
        self._has_echo = self._submitted = False

    def _input_queued(self, data: bytes) -> None:
        token = self.session.shell_token()
        if self._closed or token is None or self._active is not None:
            return
        if data.removeprefix(b"\x15").startswith(directory_key(token)):
            return
        if b"\r" in data or b"\n" in data:
            self._submitted = True

    def metadata(self, kind: str, value: str) -> None:
        if self._closed:
            return
        if kind in {"command_input", "command_input_unknown"}:
            if self._active is None:
                # Multiple echoed lines can be completion output, a heredoc or
                # pasted commands. Do not infer read-only behavior from a fragment.
                self._echo = value if kind == "command_input" and not self._has_echo else None
                self._has_echo = True
            return
        if kind != "osc":
            return
        parts = value.split(";", 3)
        if len(parts) < 3 or parts[0] != "777" or parts[2] != self.session.shell_token():
            return
        name = parts[1]
        payload = parts[3] if len(parts) == 4 else ""
        if name == "PipeTerminalCommandTypes":
            if payload == "begin":
                self._pending_types = {}
            elif payload == "end" and self._pending_types is not None:
                self._types = self._pending_types
                self._pending_types = None
        elif name == "PipeTerminalCommandType" and self._pending_types is not None:
            record = payload.split(";", 2)
            if len(record) != 3 or not record[2].endswith(";end"):
                return
            command, resolution, encoded = record
            if command not in self.session.command_names:
                return
            encoded = encoded[:-4]
            alias = None
            if "$'" not in encoded:
                try:
                    words = shlex.split(encoded)
                    if len(words) == 1:
                        alias = words[0]
                except ValueError:
                    pass
            self._pending_types[command] = resolution, alias
        elif name == "PipeTerminalCommandStart":
            self._active = (self._echo, dict(self._types))
            self._echo = None
            self._has_echo = self._submitted = False
        elif name == "PipeTerminalCommandDone":
            if not payload.isascii() or not payload.isdigit() or len(payload) > 3:
                return
            observation = self._active
            if observation is None and (self._submitted or self._has_echo):
                observation = (self._echo, dict(self._types))
            self._active = None
            self._echo = None
            self._has_echo = self._submitted = False
            if observation is not None:
                self.finished.emit(CommandObservation(observation[0], int(payload), observation[1]))

    def shutdown(self) -> None:
        self._closed = True
        self.reset()
