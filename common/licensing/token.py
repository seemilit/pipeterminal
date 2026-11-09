"""Verify signed offline licenses using bundled public keys, never secrets."""

import base64
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from uuid import UUID

from .model import LicenseError, LicenseGrant


ISSUER_ZONE = timezone(timedelta(hours=8))
_COMPACT_EPOCH = date(1970, 1, 2)
_COMPACT_PREFIX = "PT2-"
_COMPACT_DOMAIN = b"PipeTerminal-License-v2\0"
_COMPACT_HEADER_SIZE = 22
_SIGNATURE_SIZE = 64
_MAX_HOLDER_LENGTH = 256


def compact_payload(identifier: UUID, holder: str, start: date, end: date) -> bytes:
    if not _COMPACT_EPOCH <= start < end or len(holder) > _MAX_HOLDER_LENGTH:
        raise LicenseError("invalid")
    return (
        (start - _COMPACT_EPOCH).days.to_bytes(3, "big")
        + (end - _COMPACT_EPOCH).days.to_bytes(3, "big")
        + identifier.bytes
        + holder.encode("utf-8")
    )


def compact_signing_message(payload: bytes) -> bytes:
    return _COMPACT_DOMAIN + payload


def format_compact_code(payload: bytes, signature: bytes) -> str:
    if len(signature) != _SIGNATURE_SIZE:
        raise LicenseError("invalid")
    return _COMPACT_PREFIX + encode_bytes(payload + signature)


def encode_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def decode_bytes(value: str) -> bytes:
    if not value or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
        raise LicenseError("invalid")
    try:
        return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except ValueError as exc:
        raise LicenseError("invalid") from exc


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise LicenseError("invalid")
        result[key] = value
    return result


def signing_message(key_id: str, payload: bytes) -> bytes:
    if re.fullmatch(r"[a-f0-9]{16}", key_id) is None:
        raise LicenseError("invalid")
    return b"PipeTerminal-License-v1\0" + b"\x01" + bytes.fromhex(key_id) + payload


def format_code(key_id: str, payload: bytes, signature: bytes) -> str:
    signing_message(key_id, payload)
    if len(signature) != 64:
        raise LicenseError("invalid")
    encoded = base64.b32encode(b"\x01" + bytes.fromhex(key_id) + payload + signature).decode("ascii").rstrip("=")
    code = "PT1-" + "-".join(encoded[index:index + 4] for index in range(0, len(encoded), 4))
    if len(code) > 12000:
        raise LicenseError("invalid")
    return code


def _read_code(code: str):
    if not isinstance(code, str) or len(code) > 12000:
        raise LicenseError("invalid")
    compact = "".join(code.split()).replace("-", "").upper()
    if not compact.startswith("PT1") or re.fullmatch(r"[A-Z2-7]+", compact[3:]) is None:
        raise LicenseError("invalid")
    try:
        encoded = compact[3:]
        wire = base64.b32decode(encoded + "=" * (-len(encoded) % 8))
    except ValueError as exc:
        raise LicenseError("invalid") from exc
    if len(wire) <= 73 or wire[0] != 1:
        raise LicenseError("invalid")
    return wire[1:9].hex(), wire[9:-64], wire[-64:]


def verify_token(code: str, keys_path: Path) -> LicenseGrant:
    from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    if not isinstance(code, str) or len(code) > 12000:
        raise LicenseError("invalid")
    compact = "".join(code.split())
    version_two = compact[:len(_COMPACT_PREFIX)].upper() == _COMPACT_PREFIX
    if version_two:
        encoded = compact[len(_COMPACT_PREFIX):]
        wire = decode_bytes(encoded)
        minimum_size = _COMPACT_HEADER_SIZE + _SIGNATURE_SIZE
        if not minimum_size <= len(wire) <= minimum_size + 4 * _MAX_HOLDER_LENGTH or encode_bytes(wire) != encoded:
            raise LicenseError("invalid")
        payload_bytes, signature = wire[:-_SIGNATURE_SIZE], wire[-_SIGNATURE_SIZE:]
    else:
        key_id, payload_bytes, signature = _read_code(code)
    try:
        trust = json.loads(keys_path.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_object)
        keys = trust.get("keys") if isinstance(trust, dict) else None
        if not isinstance(keys, dict) or not keys:
            raise LicenseError("unconfigured")
        if version_two:
            for public_key in keys.values():
                if not isinstance(public_key, str):
                    continue
                try:
                    Ed25519PublicKey.from_public_bytes(decode_bytes(public_key)).verify(
                        signature, compact_signing_message(payload_bytes),
                    )
                except (InvalidSignature, ValueError):
                    continue
                return _compact_grant(payload_bytes)
            raise LicenseError("invalid")
        public_key = keys.get(key_id)
        if not isinstance(public_key, str):
            raise LicenseError("invalid")
        Ed25519PublicKey.from_public_bytes(decode_bytes(public_key)).verify(
            signature, signing_message(key_id, payload_bytes),
        )
        payload = json.loads(payload_bytes.decode("utf-8"), object_pairs_hook=_unique_object)
        if not isinstance(payload, dict) or type(payload.get("version")) is not int or payload["version"] != 1:
            raise LicenseError("invalid")
        if payload.get("product") != "PipeTerminal":
            raise LicenseError("invalid")
        identifier, holder = payload.get("license_id"), payload.get("holder")
        features = payload.get("capabilities")
        start, end = payload.get("not_before"), payload.get("expires_at")
        if (
            not isinstance(identifier, str) or not 1 <= len(identifier) <= 128
            or not isinstance(holder, str) or not 1 <= len(holder) <= 256
            or not isinstance(features, list) or not 1 <= len(features) <= 128
            or any(not isinstance(item, str) or not 1 <= len(item) <= 128 for item in features)
            or type(start) is not int or type(end) is not int or not 0 <= start < end < 253402300800
        ):
            raise LicenseError("invalid")
        return LicenseGrant(identifier, holder, datetime.fromtimestamp(start, timezone.utc),
                            datetime.fromtimestamp(end, timezone.utc), frozenset(features))
    except FileNotFoundError as exc:
        raise LicenseError("unconfigured") from exc
    except (InvalidSignature, UnsupportedAlgorithm, UnicodeError, ValueError, TypeError, OverflowError) as exc:
        if isinstance(exc, LicenseError):
            raise
        raise LicenseError("invalid") from exc


def _compact_grant(payload: bytes) -> LicenseGrant:
    start = _COMPACT_EPOCH + timedelta(days=int.from_bytes(payload[:3], "big"))
    end = _COMPACT_EPOCH + timedelta(days=int.from_bytes(payload[3:6], "big"))
    identifier = UUID(bytes=payload[6:_COMPACT_HEADER_SIZE])
    holder = payload[_COMPACT_HEADER_SIZE:].decode("utf-8")
    if start >= end or len(holder) > _MAX_HOLDER_LENGTH:
        raise LicenseError("invalid")
    return LicenseGrant(
        str(identifier), holder or str(identifier),
        datetime.combine(start, time.min, ISSUER_ZONE).astimezone(timezone.utc),
        datetime.combine(end, time.min, ISSUER_ZONE).astimezone(timezone.utc),
        frozenset({"*"}),
    )
