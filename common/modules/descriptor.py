"""Metadata registered by each feature's module.py entry point."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from common.i18n import tr

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


@dataclass(frozen=True)
class ModuleDescriptor:
    id: str
    name: str
    icon: str = ""
    order: int = 0
    sidebar: bool = True
    page_factory: Callable[[], QWidget] | None = None
    sidebar_position: Literal["top", "bottom"] = "top"
    on_startup: Callable[[], None] | None = None
    service_factory: Callable[[], object] | None = None
    required_capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.name.strip():
            raise ValueError(tr("模块标识和名称不能为空"))
        if self.sidebar_position not in {"top", "bottom"}:
            raise ValueError(tr("侧栏位置必须是 top 或 bottom"))
        if self.sidebar and not callable(self.page_factory):
            raise ValueError(tr("侧栏模块必须提供页面工厂"))
        if self.on_startup is not None and not callable(self.on_startup):
            raise ValueError(tr("模块启动回调必须可调用"))
        if self.service_factory is not None and not callable(self.service_factory):
            raise ValueError(tr("模块服务工厂必须可调用"))
        if not isinstance(self.required_capabilities, tuple) or any(
            not isinstance(value, str) or not value.strip() for value in self.required_capabilities
        ):
            raise ValueError(tr("所需权限必须是非空字符串元组"))
