"""QPainter cell renderer; parsing and buffer mutation belong to the engine."""

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPalette


@dataclass(frozen=True)
class CellMetrics:
    width: float
    height: float
    baseline: float
    padding: int = 8


class Renderer:
    def __init__(self, font: QFont, palette: QPalette) -> None:
        self.font = font
        metrics = QFontMetricsF(font)
        self.metrics = CellMetrics(metrics.horizontalAdvance("M"), metrics.height(), metrics.ascent())
        self.foreground = palette.color(QPalette.ColorRole.Text)
        self.background = palette.color(QPalette.ColorRole.Base)
        self.selection = palette.color(QPalette.ColorRole.Highlight)
        self.selection_text = palette.color(QPalette.ColorRole.HighlightedText)
        self.search_background = QColor("#facc15")
        self.search_current = QColor("#fb923c")
        self.search_text = QColor("#111827")
        dark = self.background.lightness() < 128
        colors = (
            ("#18181b", "#cd3131", "#0dbc79", "#e5e510", "#2472c8", "#bc3fbc", "#11a8cd", "#e5e5e5",
             "#666666", "#f14c4c", "#23d18b", "#f5f543", "#3b8eea", "#d670d6", "#29b8db", "#ffffff")
            if dark else
            ("#18181b", "#b91c1c", "#15803d", "#a16207", "#1d4ed8", "#a21caf", "#0e7490", "#4b5563",
             "#71717a", "#dc2626", "#16a34a", "#ca8a04", "#2563eb", "#c026d3", "#0891b2", "#27272a")
        )
        self.colors = [QColor(color) for color in colors]
        levels = (0, 95, 135, 175, 215, 255)
        self.colors.extend(QColor(r, g, b) for r in levels for g in levels for b in levels)
        self.colors.extend(QColor(level, level, level) for level in range(8, 239, 10))
        self._fonts: dict[tuple[bool, bool, bool], QFont] = {}

    def color(self, reference, default: QColor, bold: bool = False) -> QColor:
        if reference is None:
            return default
        if isinstance(reference, tuple):
            return QColor(*reference)
        if bold and reference < 8:
            reference += 8
        return self.colors[reference]

    def cell_rect(self, row: int, col: int, width: int = 1) -> QRectF:
        metrics = self.metrics
        return QRectF(metrics.padding + col * metrics.width, metrics.padding + row * metrics.height, metrics.width * width, metrics.height)

    def paint_line(self, painter, line, row: int, selection, search=()) -> None:
        painter.fillRect(self.cell_rect(row, 0, len(line.cells)), self.background)
        matches = {}
        for start, end, current in search:
            for col in range(max(0, start), min(len(line.cells), end)):
                matches[col] = max(matches.get(col, 0), 2 if current else 1)
        for col, cell in enumerate(line.cells):
            foreground = self.color(cell.foreground, self.foreground, cell.bold)
            background = self.color(cell.background, self.background)
            if cell.inverse:
                foreground, background = background, foreground
            if col in matches:
                background = self.search_current if matches[col] == 2 else self.search_background
            if self._selected(line.id, col - 1 if cell.continuation else col, selection):
                background = self.selection
            painter.fillRect(self.cell_rect(row, col), background)
        for col, cell in enumerate(line.cells):
            if cell.continuation or cell.text == " ":
                continue
            foreground = self.color(cell.foreground, self.foreground, cell.bold)
            background = self.color(cell.background, self.background)
            if cell.inverse:
                foreground, background = background, foreground
            if col in matches:
                foreground = self.search_text
            if self._selected(line.id, col, selection):
                foreground = self.selection_text
            key = (cell.bold, cell.italic, cell.underline)
            if key not in self._fonts:
                font = QFont(self.font)
                font.setBold(cell.bold)
                font.setItalic(cell.italic)
                font.setUnderline(cell.underline)
                self._fonts[key] = font
            rect = self.cell_rect(row, col, cell.width)
            painter.save()
            painter.setClipRect(rect)
            painter.setFont(self._fonts[key])
            painter.setPen(foreground)
            painter.drawText(QPointF(rect.left(), rect.top() + self.metrics.baseline), cell.text)
            painter.restore()

    @staticmethod
    def _selected(line_id: int, col: int, selection) -> bool:
        if selection is None:
            return False
        start, end = sorted(selection)
        return start <= (line_id, col) <= end
