"""Startup grants, persisted activation and live expiration without hot loading."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, QTimer, Signal

from .model import DevelopmentOverride, LicenseError
from .token import verify_token
from .translations import install_translations

from common.i18n import tr
from common.configuration.codec import read_text, write_text


class AuthorizationManager(QObject):
    changed = Signal()

    def __init__(self, license_path: Path, keys_path: Path, parent=None,
                 development: DevelopmentOverride | None = None) -> None:
        super().__init__(parent)
        install_translations()
        if development is not None and getattr(sys, "frozen", False):
            raise ValueError(tr("打包程序不能使用开发授权"))
        self.license_path, self.keys_path = license_path, keys_path
        self.development = development
        self.restart_required = False
        self._saved_grant = self._active_grant = None
        self._stored_error = "free"
        self._read_license()
        self._active_grant = development.grant if development is not None else self._saved_grant
        self._last_state = None
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)
        self.refresh()
        self._timer.start()

    def _read_license(self) -> None:
        try:
            record = json.loads(read_text(self.license_path))
            if not isinstance(record, dict) or not isinstance(record.get("code"), str):
                raise LicenseError("invalid")
            self._saved_grant = verify_token(record["code"], self.keys_path)
            self._stored_error = "free"
        except FileNotFoundError:
            pass
        except LicenseError as exc:
            self._stored_error = exc.reason
        except (OSError, ValueError):
            self._stored_error = "invalid"

    @property
    def active_status(self) -> str:
        if self._active_grant is None:
            return "free"
        return self._active_grant.status_at(datetime.now(timezone.utc))

    @property
    def saved_status(self) -> str:
        if self._saved_grant is None:
            return self._stored_error
        return self._saved_grant.status_at(datetime.now(timezone.utc))

    @property
    def displayed_grant(self):
        if self.development is not None and not self.restart_required:
            return self._active_grant
        return self._saved_grant

    def allows(self, capabilities) -> bool:
        if not capabilities:
            return True
        self.refresh()
        grant = self._active_grant
        return self.active_status == "valid" and grant is not None and (
            "*" in grant.capabilities or all(value in grant.capabilities for value in capabilities)
        )

    def refresh(self) -> None:
        state = (self.active_status, self.saved_status, self.restart_required)
        if state != self._last_state:
            self._last_state = state
            self.changed.emit()

    def activate(self, code: str) -> None:
        grant = verify_token(code, self.keys_path)
        status = grant.status_at(datetime.now(timezone.utc))
        if status != "valid":
            raise LicenseError(status)
        self._write_license({"code": code.strip()})
        self._saved_grant = grant
        self._stored_error = "free"
        self.restart_required = True
        self._last_state = None
        self.refresh()

    def remove(self) -> None:
        self.license_path.unlink(missing_ok=True)
        self._saved_grant = None
        self._stored_error = "free"
        self.restart_required = True
        self.refresh()

    def _write_license(self, record: dict) -> None:
        self.license_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.license_path.with_name(f".{self.license_path.name}.{uuid4().hex}.tmp")
        try:
            write_text(temporary, json.dumps(record, ensure_ascii=False, indent=2) + "\n", exclusive=True)
            temporary.replace(self.license_path)
        finally:
            temporary.unlink(missing_ok=True)
