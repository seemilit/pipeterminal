"""Immutable authorization information shared with issuer tooling."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class LicenseGrant:
    license_id: str
    holder: str
    not_before: datetime
    expires_at: datetime
    capabilities: frozenset[str]

    def status_at(self, now: datetime) -> str:
        if now < self.not_before:
            return "not_yet_valid"
        if now >= self.expires_at:
            return "expired"
        return "valid"


@dataclass(frozen=True)
class DevelopmentOverride:
    mode: str
    grant: LicenseGrant | None


class LicenseError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
