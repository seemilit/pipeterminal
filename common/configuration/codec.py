"""Versioned AES-GCM envelopes with machine binding and atomic file writes."""

import base64
import json
import os
from pathlib import Path
from uuid import uuid4

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from common.i18n import tr
from .machine import machine_binding
from .protection import protect_key, unprotect_key
from .translations import register_translations


register_translations()
FORMAT = "pipeterminal.machine-config"


class ConfigurationEncryptionError(ValueError):
    pass


def _derive(secret, salt):
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt,
                info=b"PipeTerminal/config/v1\0" + machine_binding()).derive(secret)


def _header_bytes(header):
    return json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")


def encrypt_text(content: str) -> str:
    try:
        secret, salt, nonce = os.urandom(32), os.urandom(16), os.urandom(12)
        mode, protected = protect_key(secret)
        encode = lambda value: base64.b64encode(value).decode("ascii")
        header = {"format": FORMAT, "version": 1, "cipher": "AES-256-GCM", "protection": mode,
                  "salt": encode(salt), "nonce": encode(nonce), "key": encode(protected)}
        encrypted = AESGCM(_derive(secret, salt)).encrypt(nonce, content.encode("utf-8"), _header_bytes(header))
        return json.dumps({**header, "data": encode(encrypted)}, indent=2) + "\n"
    except Exception as exc:
        raise ConfigurationEncryptionError(tr("配置加密失败，原文件未修改")) from exc


def decrypt_text(content: str) -> str:
    try:
        envelope = json.loads(content)
    except ValueError:
        if FORMAT in content:
            raise ConfigurationEncryptionError(tr("配置无法解密：不是原电脑，或文件已损坏"))
        return content
    if not isinstance(envelope, dict) or envelope.get("format") != FORMAT:
        if isinstance(envelope, dict) and {"cipher", "salt", "nonce", "key", "data"}.issubset(envelope):
            raise ConfigurationEncryptionError(tr("配置无法解密：不是原电脑，或文件已损坏"))
        return content
    try:
        if envelope.get("version") != 1 or envelope.get("cipher") != "AES-256-GCM":
            raise ValueError("Unsupported configuration version")
        header = {key: envelope[key] for key in ("format", "version", "cipher", "protection", "salt", "nonce", "key")}
        decode = lambda key: base64.b64decode(envelope[key], validate=True)
        salt, nonce, protected, data = decode("salt"), decode("nonce"), decode("key"), decode("data")
        if len(salt) != 16 or len(nonce) != 12 or len(protected) > 16384:
            raise ValueError("Invalid configuration envelope")
        secret = unprotect_key(header["protection"], protected)
        if len(secret) != 32:
            raise ValueError("Invalid configuration key")
        return AESGCM(_derive(secret, salt)).decrypt(nonce, data, _header_bytes(header)).decode("utf-8")
    except Exception as exc:
        raise ConfigurationEncryptionError(tr("配置无法解密：不是原电脑，或文件已损坏")) from exc


def read_text(path: Path) -> str:
    return decrypt_text(path.read_text(encoding="utf-8-sig"))


def write_text(path: Path, content: str, *, exclusive: bool = False) -> None:
    encrypted = encrypt_text(content)
    path.parent.mkdir(parents=True, exist_ok=True)
    target = path if exclusive else path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    created = False
    try:
        descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        created = True
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(encrypted)
            stream.flush()
            os.fsync(stream.fileno())
        if not exclusive:
            target.replace(path)
        created = False
    finally:
        if created:
            target.unlink(missing_ok=True)
