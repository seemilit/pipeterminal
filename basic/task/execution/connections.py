"""Task-owned SSH cache; never borrows a user's interactive Shell channel."""
import hashlib
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Lock, get_ident, local
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
from basic.connection.api import ServerConfigStore
from basic.shell.profile import ShellProfile
from basic.shell.host_keys import install_host_key_policy
from common.i18n import tr


class ExecutionServices(QObject):
    trust_requested = Signal(object)

    def __init__(self, config_root, parent=None):
        super().__init__(parent)
        self.store = ServerConfigStore(Path(config_root) / "host")
        self.known_hosts = Path(config_root) / "known_hosts"
        self.log_service = None
        self._clients = {}
        self._worker = local()
        self._lock = Lock()
        self._trust_lock = Lock()
        QApplication.instance().aboutToQuit.connect(self.close)
        self.destroyed.connect(lambda: self.close())

    def confirm(self, host, kind, fingerprint):
        request = dict(host=host, kind=kind, fingerprint=fingerprint, accepted=False, event=Event())
        with self._trust_lock:
            self.trust_requested.emit(request)
            return request["event"].wait(120) and request["accepted"]

    @contextmanager
    def worker_connections(self, scope):
        self._worker.key = (scope, get_ident())
        try:
            yield
        finally:
            del self._worker.key

    def close_worker_connections(self, scope):
        with self._lock:
            keys = [key for key in self._clients if key[0] is not None and key[0][0] is scope]
            clients = [self._clients.pop(key)[1] for key in keys]
        for client in clients:
            client.close()

    def connection(self, name, log):
        import paramiko
        profile = ShellProfile(name, self.store.load(name))
        profile.validate()
        config = profile.configuration
        key_file = profile.key_path() if config.auth_method == "KEY" else None
        key_stamp = (key_file.stat().st_mtime_ns, key_file.stat().st_size) if key_file else None
        fingerprint = hashlib.sha256(repr((config, key_stamp)).encode()).digest()
        cache_key = (getattr(self._worker, "key", None), name)
        with self._lock:
            saved = self._clients.get(cache_key)
            if saved and saved[0] == fingerprint:
                transport = saved[1].get_transport()
                if transport and transport.is_active() and transport.is_authenticated():
                    log(tr("复用服务器连接：{0}", name))
                    return saved[1]
            if saved:
                saved[1].close()
                del self._clients[cache_key]
        client = paramiko.SSHClient()
        install_host_key_policy(client, self.known_hosts, self.confirm)
        log(tr("正在连接服务器：{0}", name))
        try:
            client.connect(hostname=config.ip_address, port=config.port, username=config.username,
                           password=config.password if config.auth_method == "PASSWORD" else None,
                           key_filename=str(key_file) if key_file else None, timeout=20, auth_timeout=20,
                           banner_timeout=20, allow_agent=False, look_for_keys=False)
            client.get_transport().set_keepalive(30)
        except Exception:
            client.close()
            raise
        with self._lock:
            previous = self._clients.pop(cache_key, None)
            if previous:
                previous[1].close()
            self._clients[cache_key] = (fingerprint, client)
        return client

    def discard(self, client):
        with self._lock:
            for name, saved in list(self._clients.items()):
                if saved[1] is client:
                    del self._clients[name]
            client.close()

    def close(self):
        with self._lock:
            for _fingerprint, client in self._clients.values():
                client.close()
            self._clients.clear()
