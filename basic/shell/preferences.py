"""Persist Shell presentation preferences alongside application settings."""

from pathlib import Path

from common.settings.store import SettingsStore


class ShellPreferences:
    def __init__(self, settings_path: Path):
        self.store = SettingsStore(settings_path)

    def read_monitor_visible(self) -> bool:
        try:
            visible = self.store.read_section("shell").get("monitor_visible", True)
        except (OSError, ValueError):
            return True
        return visible if isinstance(visible, bool) else True

    def save_monitor_visible(self, visible: bool) -> None:
        self.store.update_section("shell", {"monitor_visible": visible})

    def read_terminal_mode(self) -> bool:
        try:
            focused = self.store.read_section("shell").get("terminal_mode", False)
        except (OSError, ValueError):
            return False
        return focused if isinstance(focused, bool) else False

    def save_terminal_mode(self, focused: bool) -> None:
        self.store.update_section("shell", {"terminal_mode": focused})
