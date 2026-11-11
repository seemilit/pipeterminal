"""Saved language selection and Qt translation refresh."""

import json
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from . import LANGUAGES, current_language, initialize, tr
from .qt import install_qt_translations
from .widgets import refresh_translations
from common.configuration.codec import ConfigurationEncryptionError, read_text, write_text


class LanguageManager(QObject):
    language_changed = Signal(str)

    def __init__(self, settings_path: Path, parent: QObject) -> None:
        super().__init__(parent)
        self.settings_path = settings_path.resolve()
        settings = self._read_settings()
        language = settings.get("language")
        if not isinstance(language, str) or language not in LANGUAGES:
            installer_language = self._read_installer_language()
            if installer_language is not None:
                language = installer_language
                try:
                    self._write_settings({**settings, "language": language})
                except OSError:
                    # Keep using the installer selection if the settings file is temporarily unwritable.
                    pass
        initialize(language)
        install_qt_translations(QApplication.instance())

    def _read_installer_language(self) -> str | None:
        try:
            value = self.settings_path.with_name("installer-language.txt").read_text(encoding="ascii").strip()
        except (OSError, UnicodeError):
            return None
        return next((language for language in LANGUAGES if language.lower() == value.lower()), None)

    def _read_settings(self) -> dict[str, object]:
        try:
            settings = json.loads(read_text(self.settings_path))
        except ConfigurationEncryptionError:
            raise
        except (OSError, ValueError):
            return {}
        return settings if isinstance(settings, dict) else {}

    def _write_settings(self, settings: dict[str, object]) -> None:
        write_text(self.settings_path, json.dumps(settings, ensure_ascii=False, indent=2) + "\n")

    def set_language(self, language: str) -> None:
        if language not in LANGUAGES:
            raise ValueError(tr("不支持的语言：{0}", language))
        self._write_settings({**self._read_settings(), "language": language})
        if language == current_language():
            return
        initialize(language)
        install_qt_translations(QApplication.instance())
        refresh_translations()
        self.language_changed.emit(language)


_manager: LanguageManager | None = None


def initialize_language(settings_path: Path, parent: QObject) -> LanguageManager:
    global _manager
    _manager = LanguageManager(settings_path, parent)
    return _manager


def get_manager() -> LanguageManager:
    if _manager is None:
        raise RuntimeError(tr("语言管理器尚未初始化"))
    return _manager
