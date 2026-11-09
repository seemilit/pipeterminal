"""Remote file labels and native icons without local filesystem lookups."""

from pathlib import PurePosixPath

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap

from common.i18n import tr

from .windows_file_icons import system_file_icon


_ARCHIVES = {".zip", ".gz", ".bz2", ".xz", ".zst", ".tar", ".tgz", ".7z", ".rar", ".jar", ".war"}
_IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".bmp", ".tif", ".tiff"}
_CODE = {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".h", ".cpp", ".hpp", ".go", ".rs", ".php", ".rb", ".sql", ".html", ".css"}
_SCRIPTS = {".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd"}
_CONFIG = {".json", ".yaml", ".yml", ".toml", ".ini", ".conf", ".cfg", ".properties", ".env", ".xml"}
_COLORS = {"file": "#64748b", "text": "#397ad5", "log": "#168595", "code": "#7851c2",
           "script": "#397452", "config": "#b97117", "archive": "#b76b31", "image": "#188573",
           "executable": "#426382", "link": "#4e73b6"}


def file_extension(name: str) -> str:
    lower = name.casefold()
    for suffix in (".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst"):
        if lower.endswith(suffix):
            return suffix
    return PurePosixPath(name).suffix.casefold()


def file_type(entry):
    if entry.link:
        return tr("链接")
    if entry.directory:
        return tr("文件夹")
    extension = file_extension(entry.name)
    if extension:
        return tr("{0} 文件", extension[1:].upper())
    return tr("可执行文件") if entry.mode & 0o111 else tr("文件")


class RemoteFileIcons:
    def __init__(self) -> None:
        self._icons = {}

    def folder_icon(self) -> QIcon:
        return self._get_icon("folder", "")

    def icon(self, entry) -> QIcon:
        if entry.directory and not entry.link:
            return self.folder_icon()
        extension = file_extension(entry.name)
        suffix = PurePosixPath(entry.name).suffix.casefold()
        if entry.link:
            kind = "link"
        elif suffix in _ARCHIVES:
            kind = "archive"
        elif suffix in _IMAGES:
            kind = "image"
        elif suffix in _CODE:
            kind = "code"
        elif suffix in _SCRIPTS:
            kind = "script"
        elif suffix in _CONFIG or entry.name in {".bashrc", ".profile", ".env"}:
            kind = "config"
        elif suffix == ".log":
            kind = "log"
        elif suffix in {".txt", ".md", ".rst", ".csv", ".tsv"}:
            kind = "text"
        else:
            kind = "executable" if entry.mode & 0o111 else "file"
        badge = extension[1:].upper() if extension else ""
        if len(badge) > 5:
            badge = suffix[1:].upper()[:5]
        return self._get_icon(kind, badge, extension=suffix)

    def _get_icon(self, kind: str, badge: str, *, extension: str = "") -> QIcon:
        key = kind, badge, extension
        if key not in self._icons:
            if len(self._icons) >= 128:
                self._icons.pop(next(iter(self._icons)))
            icon = system_file_icon(extension, directory=kind == "folder", link=kind == "link")
            self._icons[key] = icon if not icon.isNull() else self._draw_icon(kind, badge)
        return self._icons[key]

    def _draw_icon(self, kind: str, badge: str) -> QIcon:
        pixmap = QPixmap(96, 96)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(1.5, 1.5)
        if kind == "folder":
            painter.setPen(QPen(QColor("#bd811d"), 1.5))
            painter.setBrush(QColor("#e9ac3b"))
            outline = QPainterPath(QPointF(5, 16))
            for x, y in ((25, 16), (31, 22), (59, 22), (59, 53), (5, 53)):
                outline.lineTo(x, y)
            outline.closeSubpath()
            painter.drawPath(outline)
            painter.setBrush(QColor("#f6c85b"))
            painter.drawRoundedRect(QRectF(5, 26, 54, 29), 3, 3)
        else:
            color = QColor(_COLORS[kind])
            painter.setPen(QPen(color, 1.8))
            painter.setBrush(QColor("#f5f7fb"))
            outline = QPainterPath(QPointF(12, 5))
            for x, y in ((40, 5), (53, 18), (53, 58), (12, 58)):
                outline.lineTo(x, y)
            outline.closeSubpath()
            painter.drawPath(outline)
            fold = QPainterPath(QPointF(40, 5))
            fold.lineTo(40, 18)
            fold.lineTo(53, 18)
            painter.drawPath(fold)
            painter.setPen(QPen(color, 2))
            for y, end in ((25, 43), (30, 38)):
                painter.drawLine(21, y, end, y)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(7, 35, 50, 18), 3, 3)
            if badge:
                font = QFont()
                font.setPixelSize(9 if len(badge) > 3 else 11)
                font.setBold(True)
                painter.setFont(font)
                painter.setPen(QColor("#ffffff"))
                painter.drawText(QRectF(8, 35, 48, 18), Qt.AlignmentFlag.AlignCenter, badge)
            else:
                painter.setPen(QPen(QColor("#ffffff"), 2))
                if kind in {"executable", "script", "code"}:
                    painter.drawLine(22, 39, 27, 44)
                    painter.drawLine(27, 44, 22, 49)
                    painter.drawLine(32, 49, 41, 49)
                else:
                    painter.drawLine(19, 41, 45, 41)
                    painter.drawLine(19, 47, 39, 47)
            if kind == "link":
                painter.setPen(QPen(QColor("#ffffff"), 3))
                painter.drawLine(35, 49, 45, 39)
                painter.drawLine(38, 39, 45, 39)
                painter.drawLine(45, 39, 45, 46)
        painter.end()
        return QIcon(pixmap)
