"""Explicit host-key trust, retaining the original confirmation/write policy."""

import base64
import hashlib
import os
import threading
from contextlib import contextmanager
from pathlib import Path

from common.i18n import tr


_LOCK = threading.Lock()


@contextmanager
def host_key_lock(path: Path):
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.with_name(path.name + ".lock").open("a+b") as handle:
            if os.name == "nt":
                import msvcrt

                handle.seek(0, 2)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def install_host_key_policy(client, path: Path, confirm) -> None:
    import paramiko

    if path.is_file():
        client.load_host_keys(str(path))

    class ConfirmingPolicy(paramiko.MissingHostKeyPolicy):
        def missing_host_key(self, ssh_client, hostname, key):
            fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode("ascii").rstrip("=")
            if not confirm(hostname, key.get_name(), fingerprint):
                raise paramiko.SSHException(tr("未批准服务器主机密钥"))
            with host_key_lock(path):
                if path.is_file():
                    ssh_client.load_host_keys(str(path))
                saved = ssh_client.get_host_keys().lookup(hostname) or {}
                if key.get_name() in saved and saved[key.get_name()] != key:
                    raise paramiko.SSHException(tr("连接期间服务器主机密钥发生变化"))
                ssh_client.get_host_keys().add(hostname, key.get_name(), key)
                temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
                try:
                    ssh_client.get_host_keys().save(str(temporary))
                    temporary.replace(path)
                finally:
                    temporary.unlink(missing_ok=True)

    client.set_missing_host_key_policy(ConfirmingPolicy())
