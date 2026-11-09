"""The connection configuration feature's only registration entry point."""

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
    from .page import ConnectionPage
    from .store import ServerConfigStore

    root = (
        Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parents[2]
    )
    return ConnectionPage(ServerConfigStore(root / "conf" / "host"))


def get_module() -> ModuleDescriptor:
    return ModuleDescriptor(
        id="connection", name="配置", icon="connection", order=300,
        page_factory=create_page,
        on_startup=register_translations,
    )
