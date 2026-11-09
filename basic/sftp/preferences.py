"""Persist file view preferences in the existing application settings."""

import sys
from pathlib import Path

from common.settings.store import SettingsStore

from .file_grid import FILE_VIEW_MODES


class FileViewPreferences:
    def __init__(self) -> None:
        root = (
            Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[2]
        )
        self.store = SettingsStore(root / "conf" / "settings.json")

    def read_mode(self) -> str | None:
        try:
            mode = self.store.read_section("sftp").get("view_mode")
        except (OSError, ValueError):
            return None
        return mode if isinstance(mode, str) and mode in dict(FILE_VIEW_MODES) else None

    def save_mode(self, mode: str) -> None:
        self.store.update_section("sftp", {"view_mode": mode})

    def read_display_mode(self) -> str:
        try:
            mode = self.store.read_section("sftp").get("display_mode")
        except (OSError, ValueError):
            return "standalone"
        return mode if isinstance(mode, str) and mode in {"standalone", "window"} else "standalone"

    def save_display_mode(self, mode: str) -> None:
        if mode in {"standalone", "window"}:
            self.store.update_section("sftp", {"display_mode": mode})
