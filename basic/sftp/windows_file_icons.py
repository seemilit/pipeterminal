"""Windows association icons by extension, without accessing a remote path."""

import ctypes
import sys
from ctypes import wintypes
from functools import lru_cache

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QImage, QPixmap


class _ShellFileInfo(ctypes.Structure):
    _fields_ = [
        ("hIcon", wintypes.HICON), ("iIcon", ctypes.c_int),
        ("dwAttributes", wintypes.DWORD), ("szDisplayName", ctypes.c_wchar * 260),
        ("szTypeName", ctypes.c_wchar * 80),
    ]


@lru_cache(maxsize=1)
def _shell_api():
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    user = ctypes.WinDLL("user32", use_last_error=True)
    ole = ctypes.WinDLL("ole32", use_last_error=True)
    shell.SHGetFileInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                    ctypes.POINTER(_ShellFileInfo), wintypes.UINT, wintypes.UINT]
    shell.SHGetFileInfoW.restype = ctypes.c_size_t
    user.DestroyIcon.argtypes = [wintypes.HICON]
    user.DestroyIcon.restype = wintypes.BOOL
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    return shell, user, ole


def system_file_icon(extension: str, *, directory: bool = False, link: bool = False) -> QIcon:
    icon = QIcon()
    if sys.platform != "win32" or not hasattr(QImage, "fromHICON"):
        return icon
    try:
        shell, user, ole = _shell_api()
    except (OSError, AttributeError):
        return icon
    result = ole.CoInitializeEx(None, 0x2)
    if result not in {0, 1, -2147417850}:
        return icon
    initialized = result in {0, 1}
    try:
        # SHGFI_USEFILEATTRIBUTES asks for the registered type icon only.
        attributes = 0x10 if directory else 0x80
        name = "folder" if directory else extension or "file"
        flags = 0x100 | 0x10 | (0x8000 if link else 0)
        for size_flag in (1, 0):
            info = _ShellFileInfo()
            try:
                found = shell.SHGetFileInfoW(name, attributes, ctypes.byref(info), ctypes.sizeof(info), flags | size_flag)
                if found and info.hIcon:
                    image = QImage.fromHICON(info.hIcon)
                    if not image.isNull():
                        icon.addPixmap(QPixmap.fromImage(image))
                        if size_flag == 0:
                            icon.addPixmap(QPixmap.fromImage(image.scaled(
                                96, 96, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
                            )))
            finally:
                if info.hIcon:
                    user.DestroyIcon(info.hIcon)
    finally:
        if initialized:
            ole.CoUninitialize()
    return icon
