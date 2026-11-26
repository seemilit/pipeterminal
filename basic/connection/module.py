"""The connection configuration feature's only registration entry point."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from common.modules.descriptor import ModuleDescriptor, WorkspaceDirectory

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


def register_translations() -> None:
    from common.i18n import register_messages
    from .translations import MESSAGES

    for language, messages in MESSAGES.items():
        register_messages(language, messages)


def _store():
    from .store import ServerConfigStore

    root = (
        Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parents[2]
    )
    return ServerConfigStore(root / "conf" / "host")


def create_page() -> QWidget:
    from .page import ConnectionPage

    return ConnectionPage(_store())


def create_preferences():
    from .preferences import ConnectionFormPreferences

    return ConnectionFormPreferences()


def get_module() -> ModuleDescriptor:
    return ModuleDescriptor(
        id="connection", name="配置", icon="connection", order=300,
        page_factory=create_page,
        service_factory=create_preferences,
        page_kind="home",
        workspace_directory=WorkspaceDirectory(
            "服务器", lambda: _store().list_names(), lambda page, name: page.open_workflow_shell(name),
            tab_label="命令终端",
        ),
        on_startup=register_translations,
    )
