"""Log module registration, lazy viewer and lightweight service factory."""

from __future__ import annotations

import sys
from pathlib import Path
from common.modules.descriptor import ModuleDescriptor


def create_service():
    from .service import LogService
    from .store import LogStore

    root = (
        Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parents[2]
    )
    return LogService(LogStore(root / "conf" / ".logs"))


def register_translations() -> None:
    from common.i18n import register_messages
    from .translations import MESSAGES

    for language, messages in MESSAGES.items():
        register_messages(language, messages)


def get_module() -> ModuleDescriptor:
    return ModuleDescriptor(
        id="log", name="日志", icon="log", order=500,
        sidebar=False, service_factory=create_service,
        on_startup=register_translations,
    )
