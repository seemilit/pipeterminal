"""Merge one settings section without replacing other feature preferences."""

import json
from pathlib import Path
from uuid import uuid4

from common.i18n import tr
from common.configuration.codec import read_text, write_text


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def read(self) -> dict[str, object]:
        try:
            content = read_text(self.path)
        except FileNotFoundError:
            return {}
        settings = json.loads(content)
        if not isinstance(settings, dict):
            raise ValueError(tr("设置文件必须包含 JSON 对象"))
        return settings

    def read_section(self, name: str) -> dict[str, object]:
        section = self.read().get(name)
        return section if isinstance(section, dict) else {}

    def update_section(self, name: str, values: dict[str, object]) -> None:
        settings = self.read()
        section = settings.get(name)
        settings[name] = {**(section if isinstance(section, dict) else {}), **values}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        try:
            write_text(temporary, json.dumps(settings, ensure_ascii=False, indent=2) + "\n", exclusive=True)
            temporary.replace(self.path)
        except OSError:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise
