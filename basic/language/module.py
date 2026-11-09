"""The language feature's only system registration entry point."""

from __future__ import annotations

from typing import TYPE_CHECKING

from common.modules.descriptor import ModuleDescriptor

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


def create_page() -> QWidget:
    from .dialog import LanguageDialog

    return LanguageDialog()


def get_module() -> ModuleDescriptor:
    return ModuleDescriptor(
        id="language",
        name="语言",
        icon="language",
        order=900,
        sidebar=True,
        sidebar_position="bottom",
        page_factory=create_page,
    )
