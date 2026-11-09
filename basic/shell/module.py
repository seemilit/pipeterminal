"""Shell is an independent feature presented through the configuration page."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from common.modules.descriptor import ModuleDescriptor

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


def register_translations() -> None:
    from common.i18n import register_messages
    from .translations import MESSAGES

    for language, messages in MESSAGES.items():
        register_messages(language, messages)


def create_page() -> QWidget:
    from basic.connection.api import ServerConfigStore
    from .page import ShellPage

    root = (
        Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parents[2]
    )
    return ShellPage(ServerConfigStore(root / "conf" / "host"), root / "conf" / "known_hosts")


def get_module() -> ModuleDescriptor:
    return ModuleDescriptor(
        id="shell", name="命令终端", icon="terminal", order=410, sidebar=False,
        page_factory=create_page, on_startup=register_translations,
    )
