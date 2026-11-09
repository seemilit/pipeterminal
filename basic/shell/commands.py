"""Bounded auxiliary command execution on a captured SSH transport."""

import socket
import time
from dataclasses import dataclass
from threading import Event, Thread
from typing import Any

from common.i18n import tr


@dataclass(frozen=True)
class AuxiliaryCommandRunner:
    transport: Any
    connection_stop: Event

    def run(self, command: str, cancel: Event, timeout: float = 10.0, *, stdin_data: bytes | None = None) -> str:
        """Worker-only API; never reads or writes the interactive PTY channel."""
        if stdin_data is not None and len(stdin_data) > 1024 * 1024:
            raise ValueError(tr("SSH 脚本超过 1 MB 输入限制"))
        deadline = time.monotonic() + timeout
        channel = None
        finished = Event()
        try:
            self._check_cancelled(cancel, deadline)
            channel = self.transport.open_session(timeout=min(timeout, 5.0))
            channel.settimeout(1.0)
            self._check_cancelled(cancel, deadline)
            Thread(
                target=self._watch_command, args=(channel, cancel, finished, deadline),
                name="ssh-command-watch", daemon=True,
            ).start()
            channel.exec_command(command)
            if stdin_data is not None:
                offset = 0
                while offset < len(stdin_data):
                    self._check_cancelled(cancel, deadline)
                    try:
                        sent = channel.send(stdin_data[offset:offset + 32768])
                    except socket.timeout:
                        continue
                    if sent <= 0:
                        raise EOFError(tr("发送脚本时 SSH 通道已关闭"))
                    offset += sent
                channel.shutdown_write()
            output, errors, total = [], [], 0
            while True:
                self._check_cancelled(cancel, deadline)
                received = False
                for ready, receive, target in (
                    (channel.recv_ready, channel.recv, output),
                    (channel.recv_stderr_ready, channel.recv_stderr, errors),
                ):
                    if ready():
                        data = receive(16384)
                        total += len(data)
                        if total > 256 * 1024:
                            raise ValueError(tr("SSH 命令输出超过 256 KB 限制"))
                        target.append(data)
                        received = True
                if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                    status = channel.recv_exit_status()
                    break
                if channel.closed and not received:
                    raise EOFError(tr("SSH 命令通道已关闭，未收到结果"))
                if not received:
                    cancel.wait(0.02)
            if status != 0:
                detail = b"".join(errors).decode("utf-8", errors="replace").strip()
                raise RuntimeError(detail[:2048] or f"SSH command exited with status {status}")
            return b"".join(output).decode("utf-8", errors="replace")
        finally:
            finished.set()
            if channel is not None:
                try:
                    channel.close()
                except Exception:
                    pass

    def _check_cancelled(self, cancel: Event, deadline: float) -> None:
        if cancel.is_set() or self.connection_stop.is_set():
            raise ConnectionAbortedError(tr("SSH 命令已取消"))
        if time.monotonic() >= deadline:
            raise TimeoutError(tr("SSH 命令执行超时"))

    def _watch_command(self, channel, cancel, finished, deadline) -> None:
        while not finished.wait(0.1):
            if cancel.is_set() or self.connection_stop.is_set() or time.monotonic() >= deadline:
                try:
                    channel.close()
                except Exception:
                    pass
                return
