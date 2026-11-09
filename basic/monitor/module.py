"""Monitor registration; the status panel is created only when requested."""

from common.modules.descriptor import ModuleDescriptor


def create_page():
    from .panel import ServerStatusPanel

    return ServerStatusPanel()


def register_translations() -> None:
    from common.i18n import register_messages
    from .translations import MESSAGES

    for language, messages in MESSAGES.items():
        register_messages(language, messages)


def get_module() -> ModuleDescriptor:
    return ModuleDescriptor(
        id="monitor", name="监控", sidebar=False,
        page_factory=create_page, on_startup=register_translations,
    )
