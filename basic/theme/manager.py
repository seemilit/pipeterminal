"""Apply and persist the application's current theme."""

import json
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from .palettes import THEMES
from .style import build_stylesheet

from common.i18n import tr
from common.configuration.codec import ConfigurationEncryptionError, read_text, write_text


class ThemeManager(QObject):
    theme_changed = Signal(str)

    def __init__(self, settings_path: Path, application: QApplication) -> None:
        super().__init__(application)
        self.settings_path = settings_path
        self.application = application
        self.theme_id = ""
        self._translucent_workspace = False
        saved_theme = self._read_settings().get("theme", "white")
        self.apply_theme(saved_theme if isinstance(saved_theme, str) and saved_theme in THEMES else "white")

    def _read_settings(self) -> dict[str, object]:
        try:
            settings = json.loads(read_text(self.settings_path))
        except ConfigurationEncryptionError:
            raise
        except (OSError, ValueError):
            return {}
        return settings if isinstance(settings, dict) else {}

    def apply_theme(self, theme_id: str) -> None:
        if theme_id == self.theme_id:
            return
        theme = THEMES[theme_id]
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
        self.theme_id = theme_id
        self.theme_changed.emit(theme_id)

    def set_translucent_workspace(self, enabled: bool) -> None:
        if enabled != self._translucent_workspace:
            self._translucent_workspace = enabled
            self.application.setStyleSheet(build_stylesheet(THEMES[self.theme_id], translucent_workspace=enabled))

    def set_theme(self, theme_id: str) -> None:
        if theme_id not in THEMES:
            raise ValueError(tr("不支持的主题：{0}", theme_id))
        settings = {**self._read_settings(), "theme": theme_id}
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.settings_path.with_name(f".{self.settings_path.name}.tmp")
        try:
            write_text(temporary, json.dumps(settings, ensure_ascii=False, indent=2) + "\n")
            temporary.replace(self.settings_path)
        except OSError:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        self.apply_theme(theme_id)


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
