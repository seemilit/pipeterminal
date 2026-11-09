"""Server fields and validation backed by JSON-native values."""

import re
from dataclasses import dataclass

from common.i18n import tr


class ConfigurationError(ValueError):
    """A server configuration cannot be read or used."""


@dataclass(frozen=True)
class AccessPath:
    path: str = ""
    command: str = ""
    selected: bool = False
    command_enabled: bool = False


@dataclass(frozen=True)
class ServerConfiguration:
    ip_address: str = ""
    port: int = 22
    username: str = ""
    auth_method: str = "PASSWORD"
    password: str = ""
    key_filename: str = ""
    access_paths: tuple[AccessPath, ...] = ()

    @classmethod
    def from_document(cls, document: object) -> "ServerConfiguration":
        if not isinstance(document, dict):
            raise ConfigurationError(tr("服务器配置必须是 JSON 对象"))
        values: dict[str, object] = {}
        for key, value in document.items():
            normalized = key.strip().upper()
            if normalized in values:
                raise ConfigurationError(tr("配置项重复：{0}", normalized))
            values[normalized] = value
        basic_keys = {"IP_ADDRESS", "PORT", "USERNAME", "AUTH_METHOD", "PASSWORD", "KEY_FILENAME"}
        path_fields: dict[int, dict[str, object]] = {}
        for key, value in values.items():
            if key in basic_keys:
                continue
            match = re.fullmatch(r"(DEFAULT_OPEN_PATH_SELECTED|DEFAULT_OPEN_COMMAND_ENABLED|DEFAULT_OPEN_PATH|DEFAULT_OPEN_COMMAND)_([1-9][0-9]*)", key)
            if match is None:
                raise ConfigurationError(tr("不支持的配置项：{0}", key))
            path_fields.setdefault(int(match[2]), {})[match[1]] = value

        def text(key: str, default: str = "") -> str:
            value = values.get(key, default)
            if not isinstance(value, str):
                raise ConfigurationError(tr("配置项 {0} 必须是字符串", key))
            return value

        port = values.get("PORT", 22)
        if type(port) is not int or not 1 <= port <= 65535:
            raise ConfigurationError(tr("PORT 必须在 1 到 65535 之间"))
        auth_method = text("AUTH_METHOD", "PASSWORD").strip().upper()
        if auth_method not in {"PASSWORD", "KEY"}:
            raise ConfigurationError(tr("AUTH_METHOD 只能填写 PASSWORD 或 KEY"))
        access_paths = []
        for index, fields in sorted(path_fields.items()):
            path = fields.get("DEFAULT_OPEN_PATH", "")
            command = fields.get("DEFAULT_OPEN_COMMAND", "")
            selected = fields.get("DEFAULT_OPEN_PATH_SELECTED", False)
            enabled = fields.get("DEFAULT_OPEN_COMMAND_ENABLED", bool(command))
            if not isinstance(path, str) or not isinstance(command, str):
                raise ConfigurationError(tr("第 {0} 条路径和命令必须是字符串", index))
            if type(selected) is not bool or type(enabled) is not bool:
                raise ConfigurationError(tr("第 {0} 条路径选项必须是布尔值", index))
            access_paths.append(AccessPath(path, command, selected, enabled))
        return cls(
            text("IP_ADDRESS"), port, text("USERNAME"), auth_method,
            text("PASSWORD"), text("KEY_FILENAME"), tuple(access_paths),
        )

    def to_document(self) -> dict[str, object]:
        document: dict[str, object] = {
            "IP_ADDRESS": self.ip_address,
            "PORT": self.port,
            "USERNAME": self.username,
            "AUTH_METHOD": self.auth_method,
            "PASSWORD": self.password,
            "KEY_FILENAME": self.key_filename,
        }
        for index, entry in enumerate(self.access_paths, start=1):
            document.update({
                f"DEFAULT_OPEN_PATH_{index}": entry.path,
                f"DEFAULT_OPEN_COMMAND_{index}": entry.command,
                f"DEFAULT_OPEN_PATH_SELECTED_{index}": entry.selected,
                f"DEFAULT_OPEN_COMMAND_ENABLED_{index}": entry.command_enabled,
            })
        return document

    def validate(self) -> None:
        self.from_document(self.to_document())
        if sum(entry.selected for entry in self.access_paths) > 1:
            raise ConfigurationError(tr("默认访问位置只能选择一个"))
        for index, entry in enumerate(self.access_paths, start=1):
            if not entry.path.strip() and (entry.command.strip() or entry.selected or entry.command_enabled):
                raise ConfigurationError(tr("第 {0} 条访问位置缺少服务器目录", index))
