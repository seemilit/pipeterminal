"""The theme feature's only system registration entry point."""

from __future__ import annotations

from typing import TYPE_CHECKING

from common.modules.descriptor import ModuleDescriptor

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


def initialize() -> None:
    from .manager import initialize_theme

    initialize_theme()


def create_page() -> QWidget:
    from .dialog import ThemeDialog

    return ThemeDialog()


def get_module() -> ModuleDescriptor:
    return ModuleDescriptor(
        id="theme",
        name="主题",
        icon="theme",
        order=950,
        sidebar_position="bottom",
        page_factory=create_page,
        on_startup=initialize,
    )
