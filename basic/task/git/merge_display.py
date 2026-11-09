"""Align editor geometry without inserting whitespace into the document."""

def aligned_rows(texts, maps):
    center = texts[1]
    matches, insertions = {}, {}
    for side in (0, 2):
        matched, inserted = {}, {}
        for a0, a1, b0, b1 in maps.get((1, side), ([], []))[1]:
            paired = min(a1 - a0, b1 - b0)
            for offset in range(paired):
                matched[a0 + offset] = b0 + offset
            if b1 - b0 > paired:
                inserted.setdefault(a1, []).extend(range(b0 + paired, b1))
        matches[side], insertions[side] = matched, inserted
    rows = [[], [], []]
    numbers = [[], [], []]
    for line in range(len(center) + 1):
        left, right = insertions[0].get(line, []), insertions[2].get(line, [])
        for offset in range(max(len(left), len(right))):
            indexes = (left[offset] if offset < len(left) else None, None, right[offset] if offset < len(right) else None)
            for pane, index in enumerate(indexes):
                rows[pane].append(texts[pane][index] if index is not None else "")
                numbers[pane].append(index)
        if line < len(center):
            for pane, index in enumerate((matches[0].get(line), line, matches[2].get(line))):
                rows[pane].append(texts[pane][index] if index is not None else "")
                numbers[pane].append(index)
    return rows, numbers


from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QFontDatabase, QKeySequence, QPainter, QPalette, QTextBlockFormat, QTextCursor
from PySide6.QtWidgets import QTextEdit, QWidget


class _LineNumbers(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def paintEvent(self, event):
        painter = QPainter(self)
        editor = self.editor
        painter.fillRect(event.rect(), editor.palette().color(QPalette.ColorRole.AlternateBase))
        painter.setPen(editor.palette().color(QPalette.ColorRole.PlaceholderText))
        painter.setFont(editor.font())
        block = editor.cursorForPosition(editor.viewport().rect().topLeft()).block()
        while block.isValid():
            rect = editor.cursorRect(QTextCursor(block))
            if rect.top() > self.height():
                break
            if rect.bottom() >= 0:
                painter.drawText(0, rect.top(), self.width() - 6, rect.height(), Qt.AlignmentFlag.AlignRight, str(block.blockNumber() + 1))
            block = block.next()


class AlignedCodeEdit(QTextEdit):
    undo_requested = Signal()
    redo_requested = Signal()
    geometry_changed = Signal()

    def __init__(self, readonly=False):
        super().__init__()
        self.formatting = False
        self.setAcceptRichText(False)
        self.setReadOnly(readonly)
        self.setUndoRedoEnabled(False)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.document().setDocumentMargin(0)
        self.gutter = _LineNumbers(self)
        self.textChanged.connect(self._update_gutter)
        self.verticalScrollBar().valueChanged.connect(self._scrolled)
        self._update_gutter()

    def _scrolled(self, *_args):
        self.gutter.update()
        self.geometry_changed.emit()

    def _update_gutter(self):
        if self.formatting:
            return
        width = 14 + self.fontMetrics().horizontalAdvance("9") * len(str(max(1, self.document().blockCount())))
        self.setViewportMargins(width, 0, 0, 0)
        rect = self.viewport().geometry()
        self.gutter.setGeometry(self.contentsRect().left(), rect.top(), width, rect.height())
        self.gutter.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_gutter()
        self.geometry_changed.emit()

    def toPlainText(self):
        return self.document().toRawText().replace("\u2029", "\n")

    def createMimeDataFromSelection(self):
        mime = QMimeData()
        mime.setText(self.textCursor().selectedText().replace("\u2029", "\n"))
        return mime

    def keyPressEvent(self, event):
        if not self.isReadOnly() and event.matches(QKeySequence.StandardKey.Undo):
            self.undo_requested.emit()
        elif not self.isReadOnly() and event.matches(QKeySequence.StandardKey.Redo):
            self.redo_requested.emit()
        else:
            super().keyPressEvent(event)

    def align_rows(self, numbers):
        positions = {line: row for row, line in enumerate(numbers) if line is not None}
        height = self.fontMetrics().lineSpacing()
        self.formatting = True
        self.setUpdatesEnabled(False)
        transaction = QTextCursor(self.document())
        transaction.beginEditBlock()
        try:
            block = self.document().begin()
            previous_row = -1
            while block.isValid():
                number = block.blockNumber()
                row = positions.get(number, previous_row + 1)
                top = max(0, row - previous_row - 1) * height
                bottom = max(0, len(numbers) - row - 1) * height if not block.next().isValid() else 0
                cursor = QTextCursor(block)
                fmt = block.blockFormat()
                if fmt.topMargin() != top or fmt.bottomMargin() != bottom or fmt.lineHeight() != height:
                    fmt.setLineHeight(height, QTextBlockFormat.LineHeightTypes.FixedHeight.value)
                    fmt.setTopMargin(top)
                    fmt.setBottomMargin(bottom)
                    cursor.setBlockFormat(fmt)
                previous_row = row
                block = block.next()
        finally:
            transaction.endEditBlock()
            self.formatting = False
            self.setUpdatesEnabled(True)
        self._update_gutter()
        self.geometry_changed.emit()
