"""Plain-text code editor with a theme-aware line number gutter."""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFontDatabase, QPainter, QPalette, QTextFormat
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget


class _LineNumberGutter(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def paintEvent(self, event):
        self.editor.paint_line_numbers(event.rect())


class CodeEditor(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("QPlainTextEdit { border: none; padding: 0; }")
        self.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._gutter = _LineNumberGutter(self)
        self._gutter_width = 0
        self.blockCountChanged.connect(self._update_gutter_size)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self._highlight_current_line)
        self._update_font_metrics()
        self._highlight_current_line()

    def _update_font_metrics(self):
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self._update_gutter_size()

    def _update_gutter_size(self, *_args):
        digits = len(str(max(99, self.blockCount())))
        width = self.fontMetrics().horizontalAdvance("9" * digits) + 10
        if width != self._gutter_width:
            self._gutter_width = width
            self.setViewportMargins(width, 0, 0, 0)
        self._position_gutter()
        self._gutter.update()

    def _position_gutter(self):
        rect = self.viewport().geometry()
        self._gutter.setGeometry(rect.x() - self._gutter_width, rect.y(), self._gutter_width, rect.height())

    def _update_gutter(self, rect, delta):
        if delta:
            self._gutter.scroll(0, delta)
        else:
            self._gutter.update(0, rect.y(), self._gutter_width, rect.height())

    def _highlight_current_line(self):
        cursor = self.textCursor()
        cursor.clearSelection()
        selection = QTextEdit.ExtraSelection()
        selection.cursor = cursor
        selection.format.setBackground(self.palette().alternateBase())
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        self.setExtraSelections([selection])
        self._gutter.update()

    def paint_line_numbers(self, rect):
        painter = QPainter(self._gutter)
        palette = self.palette()
        painter.fillRect(rect, palette.base())
        painter.setFont(self.font())
        painter.setPen(palette.color(QPalette.ColorRole.Mid))
        painter.drawLine(self._gutter_width - 1, rect.top(), self._gutter_width - 1, rect.bottom())
        block = self.firstVisibleBlock()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        current = self.textCursor().blockNumber()
        while block.isValid() and top <= rect.bottom():
            bottom = top + self.blockBoundingRect(block).height()
            if block.isVisible() and bottom > rect.top():
                line = block.blockNumber()
                role = QPalette.ColorRole.Text if line == current else QPalette.ColorRole.PlaceholderText
                painter.setPen(palette.color(role))
                painter.drawText(
                    0, round(top), self._gutter_width - 5, max(1, round(bottom) - round(top)),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(line + 1),
                )
            block = block.next()
            top = bottom
        painter.end()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_gutter_width"):
            self._position_gutter()

    def changeEvent(self, event):
        super().changeEvent(event)
        if not hasattr(self, "_gutter_width"):
            return
        if event.type() == QEvent.Type.FontChange:
            self._update_font_metrics()
        elif event.type() == QEvent.Type.PaletteChange:
            self._highlight_current_line()
