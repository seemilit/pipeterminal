"""SFTP registers its lazy dialog through the public module registry."""

from common.modules.descriptor import ModuleDescriptor


def register_translations() -> None:
    from common.i18n import register_messages
    from .translations import MESSAGES

    for language, messages in MESSAGES.items():
        register_messages(language, messages)
    from .file_operations.translations import register_translations as register_file_translations

    register_file_translations()


def create_page():
    from .dialog import FileTransferDialog

    return FileTransferDialog()


def create_window_manager():
    from .window_manager import TransferWindowManager

    return TransferWindowManager()


def get_module() -> ModuleDescriptor:
    return ModuleDescriptor(
        id="sftp", name="文件传输", icon="file_manager", order=420,
        sidebar=False, page_factory=create_page, on_startup=register_translations,
        service_factory=create_window_manager,
    )
