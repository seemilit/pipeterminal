"""Apply and persist the application's current theme."""

import json
import sys
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from basic.terminal.palettes import DEFAULT_SHELL_THEME, SHELL_COLOR_FIELDS, SHELL_THEMES, ShellPalette

from .palettes import COLOR_FIELDS, THEMES, ThemePalette, normalize_color
from .style import build_stylesheet

from common.i18n import tr
from common.configuration.codec import ConfigurationEncryptionError, read_text, write_text


class ThemeManager(QObject):
    theme_changed = Signal(str)
    shell_theme_changed = Signal(object)

    def __init__(self, settings_path: Path, application: QApplication) -> None:
        super().__init__(application)
        self.settings_path = settings_path
        self.application = application
        self.theme_id = ""
        self._applied_theme = None
        self._translucent_workspace = False
        settings = self._read_settings()
        self.shell_themes = {**SHELL_THEMES, **self._custom_shell_themes(settings)}
        saved_shell_theme = settings.get("shell_theme")
        self.shell_theme_id = (
            saved_shell_theme
            if isinstance(saved_shell_theme, str) and saved_shell_theme in self.shell_themes
            else DEFAULT_SHELL_THEME
        )
        self.shell_palette = self.shell_themes[self.shell_theme_id]
        self.themes = {**THEMES, **self._custom_themes(settings)}
        saved_theme = settings.get("theme", "white")
        self.apply_theme(saved_theme if isinstance(saved_theme, str) and saved_theme in self.themes else "white")

    @staticmethod
    def _custom_themes(settings: dict[str, object]) -> dict[str, ThemePalette]:
        result = {}
        saved = settings.get("custom_themes")
        if not isinstance(saved, dict):
            return result
        for theme_id, entry in saved.items():
            if not theme_id.startswith("custom-") or not isinstance(entry, dict):
                continue
            name, dark = entry.get("name"), entry.get("dark")
            if not isinstance(name, str) or not name.strip() or not isinstance(dark, bool):
                continue
            try:
                colors = {key: normalize_color(entry[key]) for key, _ in COLOR_FIELDS}
            except (KeyError, ValueError):
                continue
            result[theme_id] = ThemePalette(theme_id, name, dark, **colors)
        return result

    def _read_settings(self) -> dict[str, object]:
        try:
            settings = json.loads(read_text(self.settings_path))
        except ConfigurationEncryptionError:
            raise
        except (OSError, ValueError):
            return {}
        return settings if isinstance(settings, dict) else {}

    def apply_theme(self, theme_id: str) -> None:
        self.preview_theme(self.themes[theme_id])

    def preview_theme(self, theme: ThemePalette) -> None:
        if theme == self._applied_theme:
            return
        self.application.styleHints().setColorScheme(
            Qt.ColorScheme.Dark if theme.dark else Qt.ColorScheme.Light
        )
        palette = QPalette()
        for role, color in (
            (QPalette.ColorRole.Window, theme.background),
            (QPalette.ColorRole.WindowText, theme.foreground),
            (QPalette.ColorRole.Base, theme.surface),
            (QPalette.ColorRole.AlternateBase, theme.hover),
            (QPalette.ColorRole.Text, theme.foreground),
            (QPalette.ColorRole.Button, theme.surface),
            (QPalette.ColorRole.ButtonText, theme.foreground),
            (QPalette.ColorRole.ToolTipBase, theme.surface),
            (QPalette.ColorRole.ToolTipText, theme.foreground),
            (QPalette.ColorRole.Highlight, theme.accent),
            (QPalette.ColorRole.HighlightedText, theme.accent_text),
            (QPalette.ColorRole.Link, theme.accent),
            (QPalette.ColorRole.LinkVisited, theme.accent),
            (QPalette.ColorRole.PlaceholderText, theme.muted),
            (QPalette.ColorRole.Mid, theme.border),
            (QPalette.ColorRole.Dark, theme.sidebar),
            (QPalette.ColorRole.Light, theme.border),
            (QPalette.ColorRole.Shadow, theme.border),
            (QPalette.ColorRole.Accent, theme.accent),
        ):
            palette.setColor(role, QColor(color))
        for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
            palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(theme.muted))
        self.application.setPalette(palette)
        self.application.setStyleSheet(build_stylesheet(theme, translucent_workspace=self._translucent_workspace))
        self._applied_theme = theme
        self.theme_id = theme.id
        self.theme_changed.emit(theme.id)

    def set_translucent_workspace(self, enabled: bool) -> None:
        if enabled != self._translucent_workspace:
            self._translucent_workspace = enabled
            self.application.setStyleSheet(build_stylesheet(self._applied_theme, translucent_workspace=enabled))

    def apply_shell_theme(self, theme_id: str) -> None:
        theme = self.shell_themes[theme_id]
        self.shell_theme_id = theme_id
        self.preview_shell_theme(theme)

    def preview_shell_theme(self, theme: ShellPalette) -> None:
        if theme != self.shell_palette:
            self.shell_palette = theme
            self.shell_theme_changed.emit(theme)

    @staticmethod
    def _custom_shell_themes(settings: dict[str, object]) -> dict[str, ShellPalette]:
        saved = settings.get("custom_shell_themes")
        if not isinstance(saved, dict):
            return {}
        themes = {}
        for theme_id, entry in saved.items():
            if not theme_id.startswith("custom-") or not isinstance(entry, dict):
                continue
            name, ansi = entry.get("name"), entry.get("ansi")
            if not isinstance(name, str) or not name.strip() or not isinstance(ansi, list) or len(ansi) != 16:
                continue
            try:
                colors = {key: normalize_color(entry[key]) for key, _ in SHELL_COLOR_FIELDS}
                themes[theme_id] = ShellPalette(name=name, ansi=tuple(map(normalize_color, ansi)), **colors)
            except (KeyError, ValueError):
                continue
        return themes

    def save_custom_shell_theme(self, theme_id: str, theme: ShellPalette) -> None:
        settings = self._read_settings()
        custom = self._custom_shell_themes(settings)
        custom[theme_id] = theme
        settings["custom_shell_themes"] = {key: asdict(value) for key, value in custom.items()}
        settings["shell_theme"] = theme_id
        self._write_settings(settings)
        self.shell_themes[theme_id] = theme
        self.apply_shell_theme(theme_id)

    def set_theme(self, theme_id: str, *, shell_theme_id: str | None = None) -> None:
        if theme_id not in self.themes:
            raise ValueError(tr("不支持的主题：{0}", theme_id))
        if shell_theme_id is not None and shell_theme_id not in self.shell_themes:
            raise ValueError(tr("不支持的主题：{0}", shell_theme_id))
        settings = {**self._read_settings(), "theme": theme_id}
        if shell_theme_id is not None:
            settings["shell_theme"] = shell_theme_id
        self._write_settings(settings)
        self.apply_theme(theme_id)
        if shell_theme_id is not None:
            self.apply_shell_theme(shell_theme_id)

    def save_custom_theme(self, theme: ThemePalette) -> None:
        settings = self._read_settings()
        custom = self._custom_themes(settings)
        custom[theme.id] = theme
        settings["custom_themes"] = {key: asdict(value) for key, value in custom.items()}
        settings["theme"] = theme.id
        self._write_settings(settings)
        self.themes[theme.id] = theme
        self.apply_theme(theme.id)

    def _write_settings(self, settings: dict[str, object]) -> None:
        write_text(self.settings_path, json.dumps(settings, ensure_ascii=False, indent=2) + "\n")


_manager: ThemeManager | None = None


def initialize_theme() -> None:
    global _manager
    if _manager is None:
        application = QApplication.instance()
        root = (
            Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[2]
        )
        _manager = ThemeManager(root / "conf" / "settings.json", application)


def get_manager() -> ThemeManager:
    if _manager is None:
        raise RuntimeError(tr("主题管理器尚未初始化"))
    return _manager
