"""Per-Shell search controls that never send keystrokes to SSH."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QToolButton

from common.i18n import tr
from common.i18n.widgets import QLabel, QLineEdit


class TerminalSearchBar(QFrame):
    def __init__(self, terminal, shell):
        super().__init__(shell)
        self.terminal = terminal
        self.search = terminal.search
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(4)
        layout.addStretch(1)
        self.input = QLineEdit()
        self.input.setPlaceholderText(tr("查找终端内容"))
        self.input.setMinimumWidth(160)
        self.input.setMaximumWidth(420)
        self.input.setClearButtonEnabled(True)
        self.input.textChanged.connect(self._query_changed)
        self.input.returnPressed.connect(self._enter)
        layout.addWidget(self.input, 1)
        self.case = QToolButton()
        self.case.setText("Aa")
        self.case.setCheckable(True)
        self.case.setToolTip(tr("区分大小写"))
        self.case.toggled.connect(self._query_changed)
        layout.addWidget(self.case)
        self.count = QLabel("0/0")
        self.count.setMinimumWidth(64)
        layout.addWidget(self.count)
        self.previous = QToolButton()
        self.previous.setText("↑")
        self.previous.setToolTip(tr("上一个匹配（Shift+Enter）"))
        self.previous.clicked.connect(lambda: self.search.move(-1))
        layout.addWidget(self.previous)
        self.next = QToolButton()
        self.next.setText("↓")
        self.next.setToolTip(tr("下一个匹配（Enter）"))
        self.next.clicked.connect(lambda: self.search.move(1))
        layout.addWidget(self.next)
        close = QToolButton()
        close.setText("×")
        close.setToolTip(tr("关闭搜索（Esc）"))
        close.clicked.connect(self.close_search)
        layout.addWidget(close)
        for button in (self.case, self.previous, self.next, close):
            button.setFixedSize(28, 26)
        self._find_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Find), shell)
        self._find_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._find_shortcut.activated.connect(self.open_search)
        self._escape_shortcut = QShortcut(QKeySequence("Esc"), self)
        self._escape_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._escape_shortcut.activated.connect(self.close_search)
        self._navigation_shortcuts = []
        for key, direction in (("Up", -1), ("Down", 1)):
            shortcut = QShortcut(QKeySequence(key), self.input)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(lambda value=direction: self.search.move(value))
            self._navigation_shortcuts.append(shortcut)
        self.search.changed.connect(self._update_count)
        self._update_count()
        self.hide()

    def open_search(self):
        self.show()
        selected = self.terminal.selected_text()
        if selected and "\n" not in selected and len(selected) <= 512:
            self.input.setText(selected)
        self._query_changed()
        self.input.setFocus()
        self.input.selectAll()

    def close_search(self):
        self.hide()
        self.search.set_query("")
        self.terminal.focus_terminal()

    def _query_changed(self, *_args):
        self.search.set_query(self.input.text(), self.case.isChecked())

    def _enter(self):
        direction = -1 if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        self.search.move(direction)

    def _update_count(self):
        total = len(self.search.matches)
        if self.search.scanning:
            self.count.setText(tr("正在查找…"))
        else:
            self.count.setText(f"{self.search.current_index + 1}/{total}" + ("+" if self.search.limited else ""))
        self.count.setToolTip(tr("匹配过多，请输入更具体的内容") if self.search.limited else "")
        self.previous.setEnabled(total > 0)
        self.next.setEnabled(total > 0)
