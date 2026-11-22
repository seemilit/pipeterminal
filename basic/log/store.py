"""Dated UTF-8 log paths with bounded reads and directory-safe deletion."""

import json
import re
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import TextIO
from uuid import uuid4

from common.i18n import ROWS, tr


SERVER_LOG_KINDS = {"shell": "连接记录", "sftp": "文件传输", "configuration": "配置操作"}
_LEGACY_CONNECTION = next(row for row in ROWS if row[0] == "正在连接：{0}")
_LEGACY_EVENT = re.compile(r"^\[[^\]\n]+\] \[([^\]\n]+)\] (.*)$")


class LogStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve()

    def new_path(self, category: str, name: str, *, resource: str | None = None) -> Path:
        now = datetime.now()
        safe_category = re.sub(r"[^\w.-]", "_", category)[:32] or "session"
        safe_name = re.sub(r"[^\w.-]", "_", name)[:80] or "session"
        suffix = uuid4().hex[:8]
        directory = f"{now:%Y%m%d}"
        if resource is not None:
            directory += "/" + self._resource_folder(resource)
        identifier = f"{directory}/{safe_category}_{safe_name}_{now:%H%M%S%f}_{suffix}.log"
        return self.path_for(identifier)

    def reserve_task_log(self, name: str) -> tuple[Path, TextIO]:
        now = datetime.now()
        safe_name = re.sub(r"[^\w.-]", "_", name)[:16] or "task"
        prefix = f"{safe_name}_{now:%Y-%m-%d}_"
        directory = self.path_for(f"{now:%Y%m%d}/{prefix}001.log").parent
        directory.mkdir(parents=True, exist_ok=True)
        sequence = 1
        for existing in directory.glob(f"{prefix}*.log"):
            number = existing.stem[len(prefix):]
            if number.isascii() and number.isdecimal():
                sequence = max(sequence, int(number) + 1)
        while True:
            path = self.path_for(f"{now:%Y%m%d}/{prefix}{sequence:03d}.log")
            try:
                return path, path.open("x", encoding="utf-8")
            except FileExistsError:
                sequence += 1

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
                result.append((identifier, path.stem))
        return result

    @staticmethod
    def _resource_folder(resource: str) -> str:
        return "resource-" + sha256(resource.encode("utf-8")).hexdigest()

    def server_logs(self, name: str, category: str | None = None) -> list[tuple[str, str]]:
        folder = self._resource_folder(name)
        matches = []
        for identifier, label in self.list_logs():
            parts = identifier.split("/")
            kind = label.split("_", 1)[0]
            if kind not in SERVER_LOG_KINDS or (category is not None and kind != category):
                continue
            try:
                if len(parts) == 3 and parts[1] == folder:
                    matches.append((identifier, label))
                elif len(parts) == 2 and kind == "shell" and self._legacy_shell_matches(identifier, name):
                    matches.append((identifier, label))
                elif len(parts) == 2 and kind == "configuration" and self._configuration_lines(identifier, name)[0]:
                    matches.append((identifier, label))
            except OSError:
                continue
        return sorted(matches, key=lambda row: (row[0].split("/", 1)[0], row[1].rsplit("_", 2)[-2]), reverse=True)

    def _legacy_shell_matches(self, identifier: str, name: str) -> bool:
        with self.path_for(identifier).open("rb") as handle:
            line = handle.readline(4096).decode("utf-8", errors="replace").rstrip("\r\n")
        event = _LEGACY_EVENT.fullmatch(line)
        return event is not None and event[1] == "connection" and any(
            event[2] == pattern.format(name) for pattern in _LEGACY_CONNECTION
        )

    def _configuration_lines(self, identifier: str, name: str) -> tuple[list[str], bool]:
        content, truncated = self.read(identifier)
        lines = []
        for line in content.splitlines(keepends=True):
            event = _LEGACY_EVENT.fullmatch(line.rstrip("\r\n"))
            if event is None:
                continue
            try:
                record = json.loads(event[2])
            except ValueError:
                continue
            if isinstance(record, dict) and record.get("configuration") == name:
                lines.append(line)
        return lines, truncated

    def read_server_log(self, identifier: str, name: str) -> tuple[str, bool]:
        parts = identifier.split("/")
        if len(parts) == 3 and parts[1] == self._resource_folder(name):
            return self.read(identifier)
        if len(parts) == 2:
            if parts[-1].startswith("configuration_"):
                lines, truncated = self._configuration_lines(identifier, name)
                return "".join(lines), truncated
            if parts[-1].startswith("shell_") and self._legacy_shell_matches(identifier, name):
                return self.read(identifier)
        raise ValueError(tr("日志路径必须位于日志目录内"))

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
