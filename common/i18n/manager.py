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
        initialize(self._read_settings().get("language"))
        install_qt_translations(QApplication.instance())

    def _read_settings(self) -> dict[str, object]:
        try:
            settings = json.loads(read_text(self.settings_path))
        except ConfigurationEncryptionError:
            raise
        except (OSError, ValueError):
            return {}
        return settings if isinstance(settings, dict) else {}

    def set_language(self, language: str) -> None:
        if language not in LANGUAGES:
            raise ValueError(tr("不支持的语言：{0}", language))
        settings = {**self._read_settings(), "language": language}
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
