"""Task workspace registration and lazy page creation."""

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
    from .execution.translations import MESSAGES as EXECUTION_MESSAGES

    for language, messages in MESSAGES.items():
        register_messages(language, messages)
        register_messages(language, EXECUTION_MESSAGES[language])


def _store():
    from .store import TaskStore

    root = (
        Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parents[2]
    )
    return TaskStore(root / "conf" / "tasks")


def create_page() -> QWidget:
    from .page import TaskPage

    return TaskPage(_store())


def get_module() -> ModuleDescriptor:
    return ModuleDescriptor(
        id="task", name="任务", icon="log", order=200,
        page_factory=create_page, on_startup=register_translations,
        page_kind="home",
        workspace_directory=WorkspaceDirectory(
            "流程执行", lambda: _store().list_names(), lambda page, name: page.open_execution_page(name), order=-10,
        ),
    )
