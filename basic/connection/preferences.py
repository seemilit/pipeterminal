"""Presentation preferences kept separate from server configuration data."""

import sys
from pathlib import Path

from common.settings.store import SettingsStore


class ConnectionFormPreferences:
    def __init__(self):
        root = (
            Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[2]
        )
        self.store = SettingsStore(root / "conf" / "settings.json")

    def read_basic_parameters_visible(self) -> bool:
        try:
            visible = self.store.read_section("connection").get("basic_parameters_visible", True)
        except (OSError, ValueError):
            return True
        return visible if isinstance(visible, bool) else True

    def save_basic_parameters_visible(self, visible: bool) -> None:
        self.store.update_section("connection", {"basic_parameters_visible": visible})
