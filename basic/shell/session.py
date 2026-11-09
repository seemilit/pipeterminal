"""Background SSH I/O and bounded, frame-batched GUI delivery of raw bytes."""

import socket
import time
from pathlib import Path
from queue import Empty, Full
from threading import Thread

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtWidgets import QApplication

from .connector import open_channel
from .profile import ShellProfile
from .runtime import ConnectionRun, HostKeyRequest

from common.i18n import tr

from common.i18n.errors import error_message


class SSHSession(QObject):
    dataReceived = Signal(bytes)
    dataEnded = Signal()
    connected = Signal()
    disconnected = Signal(str)
    errorOccurred = Signal(str)
    hostKeyRequested = Signal(object)
    inputQueued = Signal(bytes)
    _wake = Signal()
    _connection_ready = Signal(object)

    def __init__(self, known_hosts: Path, parent=None) -> None:
        super().__init__(parent)
        self.known_hosts = known_hosts
        self.state = "idle"
        self._run: ConnectionRun | None = None
        self._size = (80, 24)
        self.output_observer = None
        self.command_names: tuple[str, ...] = ()
        self.prompt_extension = None
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._drain)
        self._wake.connect(self._on_wake, Qt.ConnectionType.QueuedConnection)
        self._connection_ready.connect(self._on_connected, Qt.ConnectionType.QueuedConnection)
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        self.destroyed.connect(lambda: self._abandon())

    def connect_profile(self, profile: ShellProfile) -> None:
        profile.validate(include_files=False)
        self.disconnect_session()
        run = ConnectionRun(size=self._size, output_observer=self.output_observer, command_names=self.command_names, prompt_extension=self.prompt_extension)
        self._run, self.state = run, "connecting"
        Thread(target=self._connect_worker, args=(run, profile), name="ssh-connect", daemon=True).start()

    def attach_channel(self, channel, owns_channel: bool = False) -> None:
        """Attach an existing channel with exclusive read ownership, without login."""
        self.disconnect_session()
        run = ConnectionRun(channel=channel, owns_channel=owns_channel, size=self._size, output_observer=self.output_observer)
        self._run = run
        channel.settimeout(0.2)
        self._start_io(run)
        self._on_connected(run)

    def _connect_worker(self, run: ConnectionRun, profile: ShellProfile) -> None:
        try:
            profile.validate()
            open_channel(run, profile, self.known_hosts, lambda *values: self._confirm_key(run, *values))
            if run.stop.is_set():
                self._close_run(run)
                return
            self._start_io(run)
            self._connection_ready.emit(run)
        except Exception as exc:
            if not run.stop.is_set():
                run.error, run.done = error_message(exc), True
                self._notify(run)
            self._close_run(run)

    def _confirm_key(self, run, hostname, key_type, fingerprint) -> bool:
        request = HostKeyRequest(hostname, key_type, fingerprint, run.stop)
        self.hostKeyRequested.emit(request)
        deadline = time.monotonic() + 120
        while not request.completed.wait(0.1):
            if run.stop.is_set() or time.monotonic() >= deadline:
                return False
        return request.accepted and not run.stop.is_set()

    def _start_io(self, run: ConnectionRun) -> None:
        Thread(target=self._reader, args=(run,), name="ssh-reader", daemon=True).start()
        Thread(target=self._writer, args=(run,), name="ssh-writer", daemon=True).start()

    def _notify(self, run: ConnectionRun) -> None:
        try:
            with run.notification_lock:
                if not run.notified:
                    run.notified = True
                    self._wake.emit()
        except RuntimeError:
            run.stop.set()

    def _reader(self, run: ConnectionRun) -> None:
        try:
            while not run.stop.is_set():
                if run.channel.recv_ready():
                    data = run.channel.recv(16384)
                    if not data:
                        break
                    if run.output_observer is not None:
                        run.output_observer(data)
                    while not run.stop.is_set():
                        try:
                            run.incoming.put(data, timeout=0.05)
                            self._notify(run)
                            break
                        except Full:
                            continue
                elif run.channel.closed or run.channel.exit_status_ready():
                    break
                else:
                    run.stop.wait(0.01)
        except Exception as exc:
            if not run.stop.is_set():
                run.error = error_message(exc)
        finally:
            run.done = True
            self._notify(run)

    def _writer(self, run: ConnectionRun) -> None:
        try:
            while not run.stop.is_set():
                if run.size != run.applied_size:
                    size = run.size
                    run.channel.resize_pty(width=size[0], height=size[1])
                    run.applied_size = size
                try:
                    data = run.outgoing.get(timeout=0.05)
                except Empty:
                    continue
                offset, deadline = 0, time.monotonic() + 30
                while offset < len(data) and not run.stop.is_set():
                    try:
                        sent = run.channel.send(data[offset:offset + 4096])
                    except socket.timeout:
                        if time.monotonic() > deadline:
                            raise TimeoutError(tr("远端 Shell 未接收输入"))
                        continue
                    if sent <= 0:
                        raise EOFError(tr("发送输入时 SSH 通道已关闭"))
                    offset += sent
                    deadline = time.monotonic() + 30
        except Exception as exc:
            if not run.stop.is_set():
                run.error, run.done = error_message(exc), True
                run.stop.set()
                self._notify(run)

    def send(self, data: bytes) -> bool:
        run = self._run
        if run is None or self.state != "connected":
            return False
        if len(data) > 1024 * 1024:
            self.errorOccurred.emit(tr("粘贴内容超过 1 MB 输入限制"))
            return False
        try:
            run.outgoing.put_nowait(data)
            self.inputQueued.emit(data)
            return True
        except Full:
            self.errorOccurred.emit(tr("输入队列已满"))
            return False

    def resize(self, columns: int, rows: int) -> None:
        self._size = max(20, columns), max(4, rows)
        if self._run is not None:
            self._run.size = self._size

    def connection_context(self):
        """Capture this connection for feature-owned auxiliary channels."""
        from .context import SSHConnectionContext

        run = self._run
        if run is None or self.state != "connected" or run.stop.is_set():
            return None
        get_transport = getattr(run.channel, "get_transport", None)
        transport = get_transport() if callable(get_transport) else None
        if transport is None or not transport.is_active():
            return None
        return SSHConnectionContext(transport, run.stop)

    def shell_token(self) -> str | None:
        return self._run.shell_token if self._run is not None else None

    def command_runner(self):
        """Capture a worker-safe executor for this connection's auxiliary channels."""
        from .commands import AuxiliaryCommandRunner

        context = self.connection_context()
        if context is None:
            return None
        return AuxiliaryCommandRunner(context.transport, context.connection_stop)

    def _on_connected(self, run: ConnectionRun) -> None:
        if run is self._run and not run.stop.is_set():
            self.state = "connected"
            self.connected.emit()

    def _on_wake(self) -> None:
        if self._run is not None and not self._timer.isActive():
            self._timer.start()

    def _drain(self) -> None:
        run = self._run
        if run is None:
            self._timer.stop()
            return
        output, total = [], 0
        while total < 65536:
            try:
                data = run.incoming.get_nowait()
            except Empty:
                break
            output.append(data)
            total += len(data)
        if output:
            self.dataReceived.emit(b"".join(output))
        with run.notification_lock:
            empty = run.incoming.empty()
            if empty:
                run.notified = False
                self._timer.stop()
        if empty and run.done:
            error = run.error
            self.disconnect_session()
            if error:
                self.errorOccurred.emit(error)

    def disconnect_session(self) -> None:
        run, self._run = self._run, None
        previous, self.state = self.state, "idle"
        self._timer.stop()
        if run is not None:
            run.stop.set()
            Thread(target=self._close_run, args=(run,), name="ssh-close", daemon=True).start()
            self.dataEnded.emit()
            if previous != "idle":
                self.disconnected.emit(run.error)

    @staticmethod
    def _close_run(run: ConnectionRun) -> None:
        for resource in (run.channel if run.owns_channel else None, run.client):
            if resource is not None:
                try:
                    resource.close()
                except Exception:
                    pass

    def _abandon(self) -> None:
        run = self._run
        if run is not None:
            run.stop.set()
            Thread(target=self._close_run, args=(run,), daemon=True).start()

    def shutdown(self) -> None:
        self.disconnect_session()
