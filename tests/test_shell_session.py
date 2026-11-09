"""Temporary fake-channel and loopback Paramiko tests; no saved user profiles."""

import os
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path
from queue import Queue

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import paramiko
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from basic.connection.api import AccessPath, ServerConfiguration
from basic.shell.page import ShellPage
from basic.shell.profile import ShellProfile
from basic.shell.session import SSHSession
from basic.terminal.api import NativeTerminalWidget
from common.i18n import current_language, initialize


class FakeChannel:
    def __init__(self):
        self.received = Queue()
        self.sent = bytearray()
        self.sizes = []
        self.closed = False
        self.eof = False

    def settimeout(self, value):
        self.timeout = value

    def recv_ready(self):
        return not self.received.empty()

    def recv(self, size):
        return self.received.get_nowait()

    def send(self, data):
        count = min(2, len(data))
        self.sent.extend(data[:count])
        return count

    def resize_pty(self, width, height):
        self.sizes.append((width, height, threading.get_ident()))

    def exit_status_ready(self):
        return self.eof

    def close(self):
        self.closed = True


class LoopbackServer(paramiko.ServerInterface):
    def __init__(self, key=None):
        self.key = key or paramiko.RSAKey.generate(2048)
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]
        self.shell = threading.Event()
        self.stop = threading.Event()
        self.sizes = []
        self.input = bytearray()
        self.transport = None
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def check_auth_password(self, username, password):
        return paramiko.AUTH_SUCCESSFUL if (username, password) == ("test", "temporary") else paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return "password"

    def check_channel_request(self, kind, channel_id):
        return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
        self.sizes.append((width, height))
        return True

    def check_channel_window_change_request(self, channel, width, height, pixelwidth, pixelheight):
        self.sizes.append((width, height))
        return True

    def check_channel_shell_request(self, channel):
        self.shell.set()
        return True

    def serve(self):
        try:
            peer, _address = self.listener.accept()
            self.transport = paramiko.Transport(peer)
            self.transport.add_server_key(self.key)
            self.transport.start_server(server=self)
            channel = self.transport.accept(5)
            if channel is None or not self.shell.wait(5):
                return
            channel.settimeout(0.1)
            channel.sendall("\x1b[31m中文\x1b[0m\r\n> ".encode())
            while not self.stop.is_set():
                try:
                    data = channel.recv(1024)
                except socket.timeout:
                    continue
                if not data:
                    break
                self.input.extend(data)
                if b"\r" in self.input:
                    channel.sendall(b"\r\nreply\r\n> ")
                    break
        except (EOFError, OSError, paramiko.SSHException):
            pass
        finally:
            if self.transport is not None:
                self.transport.close()

    def close(self):
        self.stop.set()
        if self.transport is not None:
            self.transport.close()
        self.listener.close()
        self.thread.join(timeout=1)


class SSHSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.session = SSHSession(Path(self.temporary.name) / "known_hosts")
        self.data = []
        self.errors = []
        self.session.dataReceived.connect(self.data.append)
        self.session.errorOccurred.connect(self.errors.append)

    def tearDown(self):
        self.session.shutdown()
        self.session.deleteLater()
        self.application.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.temporary.cleanup()

    def wait_until(self, condition, timeout=5):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(0.005)
        self.assertTrue(condition(), f"Timed out; errors={self.errors}")

    def test_raw_bytes_are_delivered_on_gui_thread(self):
        channel = FakeChannel()
        gui_thread = threading.get_ident()
        callbacks = []
        self.session.dataReceived.connect(lambda data: callbacks.append(threading.get_ident()))
        self.session.attach_channel(channel)
        for chunk in (b"\xe4", b"\xb8\xad", b"\x1b[31mred"):
            channel.received.put(chunk)
        self.wait_until(lambda: b"".join(self.data) == b"\xe4\xb8\xad\x1b[31mred")
        self.assertTrue(all(thread == gui_thread for thread in callbacks))

    def test_partial_send_and_resize_stay_off_gui_thread(self):
        channel = FakeChannel()
        self.session.attach_channel(channel)
        self.session.resize(110, 35)
        self.assertTrue(self.session.send("echo 中文\r".encode()))
        self.wait_until(lambda: bytes(channel.sent) == "echo 中文\r".encode() and any(size[:2] == (110, 35) for size in channel.sizes))
        self.assertTrue(all(size[2] != threading.get_ident() for size in channel.sizes))

    def test_borrowed_channel_is_not_closed(self):
        channel = FakeChannel()
        self.session.attach_channel(channel)
        self.session.disconnect_session()
        self.assertFalse(channel.closed)
        self.assertEqual(self.session.state, "idle")

    def test_eof_flushes_output_before_disconnected(self):
        channel = FakeChannel()
        events = []
        self.session.dataReceived.connect(lambda data: events.append("data"))
        self.session.disconnected.connect(lambda error: events.append("closed"))
        self.session.attach_channel(channel, owns_channel=True)
        channel.received.put(b"final output")
        channel.eof = True
        self.wait_until(lambda: self.session.state == "idle")
        self.assertEqual(b"".join(self.data), b"final output")
        self.assertEqual(events, ["data", "closed"])

    def test_loopback_paramiko_channel_and_native_engine(self):
        server = LoopbackServer()
        widget = NativeTerminalWidget()
        self.session.dataReceived.connect(widget.feed)
        requests = []

        def approve(request):
            requests.append(request)
            request.accepted = True
            request.completed.set()

        self.session.hostKeyRequested.connect(approve)
        try:
            profile = ShellProfile("temporary", ServerConfiguration(
                ip_address="127.0.0.1", port=server.port, username="test", password="temporary",
            ))
            self.session.connect_profile(profile)
            self.wait_until(lambda: self.session.state == "connected" and "中文".encode() in b"".join(self.data))
            self.assertEqual(len(requests), 1)
            self.assertTrue(requests[0].fingerprint.startswith("SHA256:"))
            self.assertEqual(widget.engine.screen.lines[0].cells[0].text, "中")
            self.assertEqual(widget.engine.screen.lines[0].cells[0].foreground, 1)
            self.session.resize(100, 30)
            self.wait_until(lambda: (100, 30) in server.sizes)
            self.assertTrue(self.session.send(b"echo test\r"))
            self.wait_until(lambda: b"reply" in b"".join(self.data))
            self.assertEqual(bytes(server.input), b"echo test\r")
            self.assertFalse(self.errors)
        finally:
            self.session.disconnect_session()
            widget.shutdown()
            widget.deleteLater()
            server.close()

    def test_rejected_host_key_is_not_saved(self):
        server = LoopbackServer()

        def reject(request):
            request.accepted = False
            request.completed.set()

        self.session.hostKeyRequested.connect(reject)
        try:
            self.session.connect_profile(ShellProfile("temporary", ServerConfiguration(
                ip_address="127.0.0.1", port=server.port, username="test", password="temporary",
            )))
            self.wait_until(lambda: bool(self.errors))
            self.assertFalse(self.session.known_hosts.exists())
        finally:
            server.close()

    def test_changed_host_key_is_rejected_without_confirmation(self):
        server = LoopbackServer()
        recorded = paramiko.HostKeys()
        recorded.add(f"[127.0.0.1]:{server.port}", "ssh-rsa", paramiko.RSAKey.generate(2048))
        recorded.save(str(self.session.known_hosts))
        original = self.session.known_hosts.read_bytes()
        requests = []
        self.session.hostKeyRequested.connect(requests.append)
        try:
            self.session.connect_profile(ShellProfile("temporary", ServerConfiguration(
                ip_address="127.0.0.1", port=server.port, username="test", password="temporary",
            )))
            self.wait_until(lambda: bool(self.errors))
            self.assertFalse(requests)
            self.assertEqual(self.session.known_hosts.read_bytes(), original)
        finally:
            server.close()

    def test_page_activation_does_not_connect_and_keeps_default_command(self):
        configuration = ServerConfiguration(
            ip_address="127.0.0.1", username="test",
            access_paths=(AccessPath("/tmp", "pwd", True, True),),
        )

        class MemoryStore:
            def list_names(self):
                return ["temporary"]

            def load(self, name):
                return configuration

        page = ShellPage(MemoryStore(), Path(self.temporary.name) / "page_hosts")
        try:
            page.activate()
            self.assertEqual(page.session.state, "idle")
            self.assertIsNone(page.session._run)
            self.assertEqual(page.servers.currentData(), "temporary")
            self.assertEqual(page.paths.currentData(), 0)
            with patch.object(page.session, "connect_profile") as connect:
                page._connect()
                profile = connect.call_args.args[0]
                self.assertEqual((profile.directory, profile.command), ("/tmp", "pwd"))
            self.assertFalse((Path(self.temporary.name) / "page_hosts").exists())
        finally:
            page.session.shutdown()
            page.terminal.shutdown()
            page.deleteLater()

    def test_language_change_updates_login_directory(self):
        from basic.shell.module import register_translations

        register_translations()

        class EmptyStore:
            def list_names(self):
                return []

        original = current_language()
        page = ShellPage(EmptyStore(), Path(self.temporary.name) / "page_hosts")
        try:
            page.activate()
            initialize("es")
            self.application.sendEvent(page, QEvent(QEvent.Type.LanguageChange))
            self.assertEqual(page.paths.itemText(0), "Directorio de inicio")
        finally:
            initialize(original)
            page.session.shutdown()
            page.terminal.shutdown()
            page.deleteLater()


if __name__ == "__main__":
    unittest.main()
