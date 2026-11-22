"""Presentation preferences kept separate from server configuration data."""

import sys
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from common.settings.store import SettingsStore


class ConnectionFormPreferences(QObject):
    username_hidden_changed = Signal(bool)

    def __init__(self):
        super().__init__()
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

    def read_username_hidden(self) -> bool:
        try:
            return self.store.read_section("connection").get("hide_username") is True
        except (OSError, ValueError):
            return False

    def save_username_hidden(self, hidden: bool) -> None:
        self.store.update_section("connection", {"hide_username": hidden})
        self.username_hidden_changed.emit(hidden)
