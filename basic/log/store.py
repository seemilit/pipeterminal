"""Dated UTF-8 log paths with bounded reads and directory-safe deletion."""

import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from common.i18n import tr


class LogStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve()

    def new_path(self, category: str, name: str) -> Path:
        now = datetime.now()
        safe_category = re.sub(r"[^\w.-]", "_", category)[:32] or "session"
        safe_name = re.sub(r"[^\w.-]", "_", name)[:80] or "session"
        identifier = now.strftime("%Y%m%d") + "/" + (
            f"{safe_category}_{safe_name}_{now:%H%M%S%f}_{uuid4().hex[:8]}.log"
        )
        return self.path_for(identifier)

    def path_for(self, identifier: str) -> Path:
        path = self.directory / identifier
        resolved = path.resolve()
        if not resolved.is_relative_to(self.directory) or path.suffix.lower() != ".log" or path.is_symlink():
            raise ValueError(tr("日志路径必须位于日志目录内"))
        return path

    def list_logs(self) -> list[tuple[str, str]]:
        if not self.directory.is_dir():
            return []
        result = []
        for path in sorted(self.directory.rglob("*.log"), reverse=True):
            if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(self.directory):
                identifier = path.relative_to(self.directory).as_posix()
                result.append((identifier, f"{path.parent.name}  {path.stem}"))
        return result

    def read(self, identifier: str, limit: int = 4 * 1024 * 1024) -> tuple[str, bool]:
        with self.path_for(identifier).open("rb") as handle:
            size = handle.seek(0, 2)
            start = max(0, size - limit)
            handle.seek(start)
            data = handle.read(limit)
        if start:
            while data and data[0] & 0xC0 == 0x80:
                data = data[1:]
        return data.decode("utf-8", errors="replace"), start > 0

    def delete(self, identifier: str) -> None:
        self.path_for(identifier).unlink()
