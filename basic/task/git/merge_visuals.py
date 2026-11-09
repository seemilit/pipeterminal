"""Lightweight syntax colors, difference overview and connector bands."""

import keyword
import re
from pathlib import PurePosixPath
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPalette, QPen, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QToolButton, QWidget


class CodeHighlighter(QSyntaxHighlighter):
    def __init__(self, document, path, palette):
        super().__init__(document)
        suffix = PurePosixPath(path).suffix.lower()
        self.python = suffix in {".py", ".pyw"}
        self.shell = suffix in {".sh", ".bash", ".zsh", ".yaml", ".yml", ".toml"}
        self.sql = suffix == ".sql"
        self.cstyle = suffix in {".c", ".h", ".cpp", ".hpp", ".cs", ".java", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".json"}
        self.enabled = self.python or self.shell or self.sql or self.cstyle
        self.words = set(keyword.kwlist) if self.python else set("if else for while return break continue class public private protected static final void int bool string import export from const let var function new null true false try catch throw async await interface package switch case default SELECT FROM WHERE INSERT UPDATE DELETE JOIN LEFT RIGHT ON GROUP BY ORDER ASC DESC CREATE TABLE AND OR NOT NULL AS BEGIN END then fi do done in function local export".split())
        dark = palette.color(QPalette.ColorRole.Base).lightness() < 128
        colors = ("#c792ea", "#a5d6a7", "#9aa7b4", "#f6bd60") if dark else ("#7b1fa2", "#237a35", "#78838e", "#a15b00")
        self.styles = []
        for color in colors:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            self.styles.append(fmt)
        self.token = re.compile(r"[A-Za-z_][A-Za-z_0-9]*|\b\d+(?:\.\d+)?\b")

    def _color(self, text, start, end, kind):
        offset = len(text[:start].encode("utf-16-le")) // 2
        length = len(text[start:end].encode("utf-16-le")) // 2
        self.setFormat(offset, length, self.styles[kind])

    def highlightBlock(self, text):
        self.setCurrentBlockState(0)
        if not self.enabled or len(text) > 20000:
            return
        index = 0
        delimiters = {1: chr(34) * 3, 2: chr(39) * 3, 3: "*/"}
        state = self.previousBlockState()
        if state in delimiters:
            end = text.find(delimiters[state])
            if end < 0:
                self._color(text, 0, len(text), 2 if state == 3 else 1)
                self.setCurrentBlockState(state)
                return
            index = end + len(delimiters[state])
            self._color(text, 0, index, 2 if state == 3 else 1)
        while index < len(text):
            if ((self.python or self.shell) and text[index] == "#") or (self.cstyle and text.startswith("//", index)) or (self.sql and text.startswith("--", index)):
                self._color(text, index, len(text), 2)
                break
            multiline = 0
            if self.python and text[index:index + 3] in (chr(34) * 3, chr(39) * 3):
                multiline = 1 if text[index] == chr(34) else 2
                opener = 3
            elif (self.cstyle or self.sql) and text.startswith("/*", index):
                multiline, opener = 3, 2
            if multiline:
                end = text.find(delimiters[multiline], index + opener)
                stop = len(text) if end < 0 else end + len(delimiters[multiline])
                self._color(text, index, stop, 2 if multiline == 3 else 1)
                if end < 0:
                    self.setCurrentBlockState(multiline)
                index = stop
                continue
            if text[index] in (chr(34), chr(39), "`"):
                quote, stop = text[index], index + 1
                while stop < len(text):
                    if text[stop] == "\\":
                        stop += 2
                    elif text[stop] == quote:
                        stop += 1
                        break
                    else:
                        stop += 1
                self._color(text, index, min(stop, len(text)), 1)
                index = stop
                continue
            token = self.token.match(text, index)
            if token:
                word = token.group()
                if word in self.words or (self.sql and word.upper() in self.words):
                    self._color(text, index, token.end(), 0)
                elif word[0].isdigit():
                    self._color(text, index, token.end(), 3)
                index = token.end()
            else:
                index += 1


class DifferenceOverview(QWidget):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.markers = []
        self.setFixedWidth(16)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        editor.verticalScrollBar().valueChanged.connect(lambda _value: self.update())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().color(QPalette.ColorRole.AlternateBase))
        count = max(1, self.editor.document().blockCount(), self.editor.viewport().height() / max(1, self.editor.fontMetrics().lineSpacing()))
        for line, color in self.markers:
            y = min(self.height() - 3, int(line * self.height() / count))
            painter.fillRect(3, y, self.width() - 6, 3, QColor(color))

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        count = max(1, self.editor.document().blockCount(), self.editor.viewport().height() / max(1, self.editor.fontMetrics().lineSpacing()))
        line = int(event.position().y() * count / max(1, self.height()))
        if self.markers:
            line = min(self.markers, key=lambda entry: abs(entry[0] - line))[0]
        line = max(0, min(line, self.editor.document().blockCount() - 1))
        cursor = QTextCursor(self.editor.document().findBlockByNumber(line))
        self.editor.setTextCursor(cursor)
        self.editor.ensureCursorVisible()
        self.editor.setFocus()


class ConnectionLane(QWidget):
    def __init__(self):
        super().__init__()
        self.bands = []
        self.setFixedWidth(48)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        width = self.width()
        for left_top, left_bottom, right_top, right_bottom, color in self.bands:
            path = QPainterPath()
            path.moveTo(0, left_top)
            path.cubicTo(width / 2, left_top, width / 2, right_top, width, right_top)
            path.lineTo(width, right_bottom)
            path.cubicTo(width / 2, right_bottom, width / 2, left_bottom, 0, left_bottom)
            path.closeSubpath()
            painter.fillPath(path, color)


class MergeActionButton(QToolButton):
    """Font-independent, palette-aware merge toolbar and gutter icons."""

    def __init__(self, symbol, parent=None):
        super().__init__(parent)
        self._symbol = symbol
        self.setAutoRaise(True)
        self.setFixedSize(30, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("QToolButton { border: none; background: transparent; border-radius: 3px; } QToolButton:hover:enabled { background: palette(midlight); } QToolButton:pressed { background: palette(mid); }")

    def setSymbol(self, symbol):
        if self._symbol != symbol:
            self._symbol = symbol
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = min(self.width(), self.height())
        painter.translate((self.width() - size) / 2, (self.height() - size) / 2)
        painter.scale(size / 24, size / 24)
        group = QPalette.ColorGroup.Active if self.isEnabled() else QPalette.ColorGroup.Disabled
        pen = QPen(self.palette().color(group, QPalette.ColorRole.ButtonText), 1.3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        path = QPainterPath()
        symbol = self._symbol
        if symbol in {"up", "down"}:
            if symbol == "down":
                painter.translate(0, 24)
                painter.scale(1, -1)
            path.moveTo(12, 19)
            path.lineTo(12, 5)
            path.moveTo(7, 10)
            path.lineTo(12, 5)
            path.lineTo(17, 10)
        elif symbol in {"undo", "redo"}:
            if symbol == "redo":
                painter.translate(24, 0)
                painter.scale(-1, 1)
            path.moveTo(19, 18)
            path.cubicTo(21, 7, 13, 7, 5, 9)
            path.moveTo(9, 4)
            path.lineTo(5, 9)
            path.lineTo(10, 13)
        elif symbol == "ignore":
            path.moveTo(6, 6)
            path.lineTo(18, 18)
            path.moveTo(18, 6)
            path.lineTo(6, 18)
        elif symbol in {"left", "right"}:
            if symbol == "left":
                painter.translate(24, 0)
                painter.scale(-1, 1)
            for x in (5, 11):
                path.moveTo(x, 6)
                path.lineTo(x + 6, 12)
                path.lineTo(x, 18)
        elif symbol in {"both", "reverse"}:
            if symbol == "reverse":
                painter.translate(24, 0)
                painter.scale(-1, 1)
            path.moveTo(5, 7)
            path.lineTo(18, 7)
            path.moveTo(14, 3)
            path.lineTo(18, 7)
            path.lineTo(14, 11)
            path.moveTo(19, 17)
            path.lineTo(6, 17)
            path.moveTo(10, 13)
            path.lineTo(6, 17)
            path.lineTo(10, 21)
        painter.drawPath(path)
