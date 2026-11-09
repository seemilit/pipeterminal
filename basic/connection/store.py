"""Manage machine-encrypted .server.json files and plaintext in-memory models."""

import json
import re
from contextlib import contextmanager
from pathlib import Path

from common.i18n import tr
from common.configuration.codec import read_text, write_text

from .model import ConfigurationError, ServerConfiguration

from common.i18n.errors import error_message


SERVER_SUFFIX = ".server.json"


class ServerConfigStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve()
        self.log_service = None
        self.history_service = None
        self.last_history_error: str | None = None
        self.last_audit_log_path: Path | None = None

    def bind_services(self, log_service=None, history_service=None) -> None:
        self.log_service, self.history_service = log_service, history_service

    @staticmethod
    def resource_id(name: str) -> str:
        return "connection:" + name

    @contextmanager
    def _operation(self, operation: str, name: str, **details):
        self.last_history_error = None
        try:
            yield details
        except (OSError, ValueError) as exc:
            self._audit(operation, name, "failed", error=type(exc).__name__, **details)
            raise
        else:
            self._audit(operation, name, "success", **details)

    def _audit(self, operation: str, name: str, result: str, **details) -> None:
        if self.log_service is not None:
            try:
                message = json.dumps({"configuration": name, "result": result, **details}, ensure_ascii=False)
                writer = self.log_service.record_event("configuration", operation, message)
                self.last_audit_log_path = writer.path
            except (OSError, ValueError, RuntimeError):
                pass

    def _snapshot(self, name: str, content: str, reason: str, required: bool = False) -> None:
        if self.history_service is not None:
            try:
                self.history_service.snapshot(self.resource_id(name), content, reason)
            except (OSError, ValueError) as exc:
                self.last_history_error = error_message(exc)
                self._audit("history", name, "failed", error=type(exc).__name__)
                if required:
                    raise

    def ensure_history(self, name: str) -> None:
        self._snapshot(name, read_text(self.path_for(name)), "当前版本", required=True)

    def path_for(self, name: str) -> Path:
        if (
            not name or name.strip() != name or name.rstrip(". ") != name
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            or re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", name.split(".")[0], re.IGNORECASE)
        ):
            raise ConfigurationError(tr("文件名称包含 Windows 不允许的字符"))
        path = self.directory / f"{name}{SERVER_SUFFIX}"
        if path.resolve().parent != self.directory or path.is_symlink():
            raise ConfigurationError(tr("配置文件必须位于服务器配置目录内"))
        return path

    def list_names(self) -> list[str]:
        if not self.directory.is_dir():
            return []
        return sorted(
            (path.name[:-len(SERVER_SUFFIX)] for path in self.directory.glob(f"*{SERVER_SUFFIX}")
             if path.is_file() and not path.is_symlink()),
            key=str.casefold,
        )

    @staticmethod
    def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        document: dict[str, object] = {}
        for key, value in pairs:
            if key in document:
                raise ConfigurationError(tr("配置项重复：{0}", key))
            document[key] = value
        return document

    def load(self, name: str) -> ServerConfiguration:
        content = read_text(self.path_for(name))
        try:
            document = json.loads(content, object_pairs_hook=self._unique_object)
        except json.JSONDecodeError as exc:
            raise ConfigurationError(tr("配置文件不是有效的 JSON：{0}", error_message(exc))) from exc
        return ServerConfiguration.from_document(document)

    def create(self, name: str, configuration: ServerConfiguration | None = None) -> None:
        with self._operation("create", name):
            configuration = configuration if configuration is not None else ServerConfiguration()
            configuration.validate()
            path = self.path_for(name)
            if path.exists():
                raise FileExistsError(tr("配置名称已存在：{0}", name))
            self.directory.mkdir(parents=True, exist_ok=True)
            content = json.dumps(configuration.to_document(), ensure_ascii=False, indent=2) + "\n"
            write_text(path, content, exclusive=True)
            if self.history_service is not None:
                self._snapshot(name, content, "新建")

    def save(self, name: str, configuration: ServerConfiguration, *, reason: str = "保存") -> None:
        restoring = reason == "回退"
        with self._operation("restore" if restoring else "save", name) as details:
            if restoring and (self.history_service is None or not self.history_service.allowed()):
                raise ConfigurationError(tr("历史版本需要付费授权"))
            configuration.validate()
            path = self.path_for(name)
            if not path.is_file():
                raise FileNotFoundError(tr("配置文件不存在：{0}", path))
            original = read_text(path)
            self._snapshot(name, original, "回退前" if reason == "回退" else "更新前", required=True)
            document = configuration.to_document()
            try:
                previous = json.loads(original)
            except ValueError:
                previous = {}
            if isinstance(previous, dict):
                details["changed_fields"] = sorted(
                    key for key in set(previous) | set(document) if previous.get(key) != document.get(key)
                )
            content = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
            write_text(path, content)
            self._snapshot(name, content, reason)

    def rename(self, source: str, target: str) -> None:
        with self._operation("rename", source, target=target):
            source_path, target_path = self.path_for(source), self.path_for(target)
            if target_path.exists() and target_path != source_path:
                raise FileExistsError(tr("配置名称已存在：{0}", target))
            if self.history_service is not None:
                self.ensure_history(source)
            source_path.rename(target_path)
            if self.history_service is not None:
                try:
                    self.history_service.rekey(self.resource_id(source), self.resource_id(target))
                except (OSError, ValueError) as exc:
                    self.last_history_error = error_message(exc)
                    self._audit("history", target, "failed", error=type(exc).__name__)

    def copy(self, source: str, target: str) -> None:
        with self._operation("copy", target, source=source):
            source_path, target_path = self.path_for(source), self.path_for(target)
            if target_path.exists():
                raise FileExistsError(tr("配置名称已存在：{0}", target))
            content = read_text(source_path)
            write_text(target_path, content, exclusive=True)
            if self.history_service is not None:
                self._snapshot(target, content, "复制")

    def delete(self, name: str) -> None:
        with self._operation("delete", name):
            path = self.path_for(name)
            if self.history_service is not None:
                self._snapshot(name, read_text(path), "删除前", required=True)
            path.unlink()
