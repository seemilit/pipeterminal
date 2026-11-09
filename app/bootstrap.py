"""Application startup kept separate from shared Qt components."""

import ctypes
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from common.i18n.manager import initialize_language
from common.i18n import tr
from common.configuration.codec import ConfigurationEncryptionError
from common.licensing.manager import AuthorizationManager
from common.modules.loader import ModuleLoader
from common.modules.registry import ModuleRegistry

from .main_window import MainWindow
from .version import application_version


def run(module_packages: tuple[str, ...] = ("basic",), *, development_authorization=None,
        verification_keys_path: Path | None = None) -> int:
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PipeTerminal")

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)
    application = QApplication(sys.argv)
    application.setApplicationName("PipeTerminal")
    application.setStyle("Fusion")
    application_root = Path(__file__).resolve().parent.parent
    frozen = getattr(sys, "frozen", False)
    application.setApplicationVersion(application_version(application_root, frozen=frozen))
    icon_path = application_root / "resources" / "app_icon.png"
    application.setWindowIcon(QIcon(str(icon_path)))

    data_root = (
        Path(sys.executable).resolve().parent
        if frozen
        else application_root
    )
    try:
        language_manager = initialize_language(
            data_root / "conf" / "settings.json", application,
        )
    except ConfigurationEncryptionError as exc:
        QMessageBox.critical(None, tr("配置加载失败"), str(exc))
        return 1
    authorization = AuthorizationManager(
        data_root / "conf" / "license.json",
        verification_keys_path or icon_path.parent / "license_public_keys.json", application,
        development=development_authorization,
    )
    registry = ModuleRegistry(authorization)
    registry.register_service("authorization", authorization)
    window = MainWindow(registry, data_root / "conf" / "settings.json")
    language_manager.language_changed.connect(window.shell.sidebar.refresh_language)
    loader = ModuleLoader(registry)
    for package_name in module_packages:
        loader.load(package_name)
    window.load_modules()
    window.show()
    return application.exec()
