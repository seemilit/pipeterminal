"""Protect file keys with Windows machine DPAPI or a private OS key file."""

import ctypes
import os
import sys
from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _dpapi(data: bytes, decrypt: bool) -> bytes:
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    incoming = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = Blob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    operation = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                          ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    operation.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    flags = 1 if decrypt else 5  # UI forbidden; protection is scoped to this Windows machine.
    if not operation(ctypes.byref(incoming), None, None, None, None, flags, ctypes.byref(outgoing)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(outgoing.data, outgoing.size)
    finally:
        kernel32.LocalFree(outgoing.data)


@lru_cache(maxsize=1)
def _user_key() -> bytes:
    root = (
        Path.home() / "Library" / "Application Support" if sys.platform == "darwin"
        else Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    ) / "PipeTerminal" / "security"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / "configuration.key"
    if path.is_symlink():
        raise ValueError("Invalid key path")
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(os.urandom(32))
            stream.flush()
            os.fsync(stream.fileno())
    data = path.read_bytes()
    if len(data) != 32:
        raise ValueError("Invalid configuration key")
    return data


def protect_key(key: bytes) -> tuple[str, bytes]:
    if sys.platform == "win32":
        return "windows-dpapi-machine", _dpapi(key, False)
    nonce = os.urandom(12)
    return "local-user-key", nonce + AESGCM(_user_key()).encrypt(nonce, key, b"PipeTerminal/key/v1")


def unprotect_key(mode: str, protected: bytes) -> bytes:
    if mode == "windows-dpapi-machine" and sys.platform == "win32":
        return _dpapi(protected, True)
    if mode == "local-user-key" and sys.platform != "win32" and len(protected) >= 28:
        return AESGCM(_user_key()).decrypt(protected[:12], protected[12:], b"PipeTerminal/key/v1")
    raise ValueError("Unsupported key protection")
