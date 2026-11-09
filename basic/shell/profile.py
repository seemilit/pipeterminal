"""Validate saved server data for an explicitly requested connection."""

import os
from dataclasses import dataclass
from pathlib import Path

from basic.connection.api import ConfigurationError, ServerConfiguration
from common.i18n import tr


@dataclass(frozen=True)
class ShellProfile:
    name: str
    configuration: ServerConfiguration
    directory: str | None = None
    command: str | None = None

    def validate(self, include_files: bool = True) -> None:
        self.configuration.validate()
        missing = [
            label for label, value in (
                ("IP_ADDRESS", self.configuration.ip_address),
                ("USERNAME", self.configuration.username),
            ) if not value.strip()
        ]
        if missing:
            raise ConfigurationError(tr("缺少服务器配置：{0}", ", ".join(missing)))
        if self.configuration.auth_method == "KEY":
            path = self.key_path() if include_files else None
            if not self.configuration.key_filename.strip() or (include_files and not path.is_file()):
                raise ConfigurationError(tr("SSH 私钥不存在：{0}", self.configuration.key_filename))
        if self.directory and any(ord(char) < 32 or ord(char) == 127 for char in self.directory):
            raise ConfigurationError(tr("服务器目录无效"))

    def key_path(self) -> Path | None:
        value = self.configuration.key_filename.strip()
        return Path(os.path.expandvars(os.path.expanduser(value))).resolve() if value else None
