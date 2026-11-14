"""Read-only log text with a shared, non-filtering search bar."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut, QTextCursor, QTextDocument
from PySide6.QtWidgets import QApplication, QHBoxLayout, QPlainTextEdit, QTextEdit, QVBoxLayout, QWidget

from common.i18n import tr
from common.i18n.widgets import QLabel, QLineEdit, QPushButton, QToolButton


class LogViewer(QWidget):
    def __init__(self, parent, header=None) -> None:
        super().__init__(parent)
        self.text = QPlainTextEdit()
        self.text.setProperty("workspaceSurface", True)
        self.text.setReadOnly(True)
        self._match = QTextCursor()
        self._position = 0
        self._reveal_pending = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        find = QPushButton(tr("查找"))
        find.setToolTip(tr("查找日志内容（Ctrl+F）"))
        find.setAutoDefault(False)
        find.clicked.connect(self.open_search)
        if header is None:
            header = QHBoxLayout()
            header.addStretch(1)
            layout.addLayout(header)
        header.addWidget(find)

        self._bar = QWidget(self)
        row = QHBoxLayout(self._bar)
        row.setContentsMargins(0, 0, 0, 0)
        self._input = QLineEdit()
        self._input.setPlaceholderText(tr("查找日志内容"))
        self._input.setClearButtonEnabled(True)
        self._input.textChanged.connect(self._query_changed)
        self._input.returnPressed.connect(self._enter)
        row.addWidget(self._input, 1)
        self._case = self._button(row, "Aa", "区分大小写")
        self._case.setCheckable(True)
        self._case.toggled.connect(self._query_changed)
        self._status = QLabel()
        row.addWidget(self._status)
        self._previous = self._button(row, "↑", "上一个匹配（Shift+Enter）")
        self._previous.clicked.connect(lambda: self._move(True))
        self._next = self._button(row, "↓", "下一个匹配（Enter）")
        self._next.clicked.connect(lambda: self._move(False))
        close = self._button(row, "×", "关闭搜索（Esc）")
        close.clicked.connect(self.close_search)
        self._bar.hide()
        layout.addWidget(self._bar)
        layout.addWidget(self.text, 1)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(150)
        self._refresh_timer.timeout.connect(self._refresh)
        self.text.textChanged.connect(self._text_changed)
        self._find_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Find), parent)
        self._find_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._find_shortcut.activated.connect(self.open_search)
        self._find_shortcut.setEnabled(False)
        self._close_shortcut = QShortcut(QKeySequence("Esc"), parent)
        self._close_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._close_shortcut.activated.connect(self.close_search)
        self._close_shortcut.setEnabled(False)

    @staticmethod
    def _button(row, symbol, tooltip):
        button = QToolButton()
        button.setText(symbol)
        button.setToolTip(tr(tooltip))
        button.setFixedSize(28, 26)
        row.addWidget(button)
        return button

    @property
    def search_open(self) -> bool:
        return not self._bar.isHidden()

    @property
    def has_match(self) -> bool:
        return self._match.hasSelection()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._find_shortcut.setEnabled(True)
        self._close_shortcut.setEnabled(self.search_open)
        if self.search_open and self._input.text():
            self._refresh_timer.start()

    def hideEvent(self, event) -> None:
        self._find_shortcut.setEnabled(False)
        self._close_shortcut.setEnabled(False)
        self._refresh_timer.stop()
        super().hideEvent(event)

    def open_search(self) -> None:
        if not self.search_open:
            self._bar.show()
            self._close_shortcut.setEnabled(True)
            selected = self.text.textCursor().selectedText()
            if selected and "\u2029" not in selected and "\u2028" not in selected and len(selected) <= 512:
                self._input.setText(selected)
            self._query_changed()
        self._input.setFocus()
        self._input.selectAll()

    def close_search(self) -> None:
        self._bar.hide()
        self._close_shortcut.setEnabled(False)
        self._refresh_timer.stop()
        self._reveal_pending = False
        self._show_match(QTextCursor())
        self.text.setFocus()

    def _query_changed(self, *_args) -> None:
        self._refresh_timer.stop()
        self._position = self.text.textCursor().selectionStart()
        self._reveal_pending = bool(self._input.text())
        self._show_match(QTextCursor())
        if self._reveal_pending:
            self._status.setText(tr("正在查找…"))
            self._refresh_timer.start()

    def _text_changed(self) -> None:
        if self.isVisible() and self.search_open and self._input.text() and not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def _find(self, position: int, backwards: bool = False) -> QTextCursor:
        document = self.text.document()
        end = document.characterCount() - 1
        flags = QTextDocument.FindFlag.FindCaseSensitively if self._case.isChecked() else QTextDocument.FindFlag(0)
        if backwards:
            flags |= QTextDocument.FindFlag.FindBackward
        query = self._input.text()
        match = document.find(query, min(max(position, 0), end), flags)
        if match.isNull():
            match = document.find(query, end if backwards else 0, flags)
        return match

    def _refresh(self) -> None:
        reveal = self._reveal_pending
        self._reveal_pending = False
        position = self._match.selectionStart() if self._match.hasSelection() else self._position
        self._show_match(self._find(position), reveal=reveal)

    def _move(self, backwards: bool) -> None:
        if not self._input.text():
            return
        if self._reveal_pending:
            self._refresh_timer.stop()
            if not backwards:
                self._refresh()
                return
            self._reveal_pending = False
        position = self._position
        if self._match.hasSelection():
            position = self._match.selectionStart() if backwards else self._match.selectionEnd()
        self._show_match(self._find(position, backwards), reveal=True)

    def _enter(self) -> None:
        self._move(bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier))

    def _show_match(self, match: QTextCursor, *, reveal: bool = False) -> None:
        self._match = match
        found = match.hasSelection()
        selections = []
        if found:
            self._position = match.selectionStart()
            selection = QTextEdit.ExtraSelection()
            selection.cursor = match
            palette = self.text.palette()
            selection.format.setBackground(palette.highlight())
            selection.format.setForeground(palette.highlightedText())
            selections.append(selection)
            if reveal:
                cursor = QTextCursor(match)
                cursor.setPosition(self._position)
                self.text.setTextCursor(cursor)
                self.text.ensureCursorVisible()
        self.text.setExtraSelections(selections)
        self._status.setText(tr("未找到匹配") if self.search_open and self._input.text() and not found else "")
        self._previous.setEnabled(found)
        self._next.setEnabled(found)
