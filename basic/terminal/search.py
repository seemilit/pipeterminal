"""Batched read-only search over terminal cells and retained scrollback."""

import re
import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal


@dataclass(frozen=True)
class SearchMatch:
    spans: tuple[tuple[int, int, int], ...]


class TerminalSearch(QObject):
    changed = Signal()
    MAX_MATCHES = 20000

    def __init__(self, terminal):
        super().__init__(terminal)
        self.terminal = terminal
        self.query = ""
        self.matches = []
        self.current_index = -1
        self.scanning = False
        self.limited = False
        self.highlights = {}
        self._dirty = False
        self._reveal_pending = False
        self._lines = ()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._start)
        self._batch = QTimer(self)
        self._batch.setInterval(0)
        self._batch.timeout.connect(self._scan)

    def set_query(self, text, case_sensitive=False):
        self._timer.stop()
        self._batch.stop()
        self.query = text
        self.matches = []
        self.current_index = -1
        self.highlights = {}
        self.limited = self.scanning = False
        self._lines = ()
        self._text, self._positions = [], []
        self._reveal_pending = bool(text)
        if text:
            self._pattern = re.compile(re.escape(text), 0 if case_sensitive else re.IGNORECASE)
            self._timer.start(120)
        self.changed.emit()
        self.terminal.viewport().update()

    def invalidate(self):
        if self.query:
            self._dirty = True
            if not self.scanning and not self._timer.isActive():
                self._timer.start(180)

    def _start(self):
        if not self.query:
            return
        self._batch.stop()
        screen = self.terminal.engine.screen
        self._lines = tuple(screen.history) + tuple(screen.row_at(len(screen.history) + row) for row in range(screen.rows))
        self._offset = 0
        self._found = []
        self._text, self._positions = [], []
        self._dirty = False
        self.scanning = True
        self.limited = False
        self.changed.emit()
        self._batch.start()

    def _scan(self):
        deadline = time.monotonic() + 0.005
        for _ in range(100):
            if self._offset >= len(self._lines):
                if self._text:
                    self._find_group()
                self._commit()
                return
            line = self._lines[self._offset]
            self._offset += 1
            for col, cell in enumerate(line.cells):
                if not cell.continuation:
                    self._text.append(cell.text)
                    self._positions.extend([(line.id, col, col + max(1, cell.width))] * len(cell.text))
            if not line.wrapped:
                self._find_group()
            if self.limited:
                self._commit()
                return
            if time.monotonic() >= deadline:
                return

    def _find_group(self):
        text = "".join(self._text).rstrip(" ")
        for found in self._pattern.finditer(text):
            if len(self._found) >= self.MAX_MATCHES:
                self.limited = True
                break
            spans = []
            for line_id, start, end in self._positions[found.start():found.end()]:
                if spans and spans[-1][0] == line_id:
                    spans[-1] = (line_id, spans[-1][1], max(spans[-1][2], end))
                else:
                    spans.append((line_id, start, end))
            if spans:
                self._found.append(SearchMatch(tuple(spans)))
        self._text, self._positions = [], []

    def _commit(self):
        self._batch.stop()
        previous = self.matches[self.current_index] if 0 <= self.current_index < len(self.matches) else None
        self.matches = self._found
        self.current_index = -1
        if self.matches:
            try:
                self.current_index = self.matches.index(previous)
            except ValueError:
                first = self.terminal.engine.screen.row_at(self.terminal.verticalScrollBar().value()).id
                self.current_index = next((index for index, match in enumerate(self.matches) if match.spans[0][0] >= first), 0)
        self.scanning = False
        self._lines = ()
        self._update_highlights()
        if self._reveal_pending:
            self._reveal_pending = False
            self._reveal()
        self.changed.emit()
        if self._dirty:
            self._timer.start(180)

    def _update_highlights(self):
        self.highlights = {}
        for index, match in enumerate(self.matches):
            for line_id, start, end in match.spans:
                self.highlights.setdefault(line_id, []).append((start, end, index == self.current_index))
        self.terminal.viewport().update()

    def move(self, direction):
        if not self.matches:
            self._reveal_pending = True
            return
        self.current_index = (self.current_index + direction) % len(self.matches)
        self._update_highlights()
        self._reveal()
        self.changed.emit()

    def _reveal(self):
        if not 0 <= self.current_index < len(self.matches):
            return
        match = self.matches[self.current_index]
        screen = self.terminal.engine.screen
        index = screen.index_of(match.spans[0][0])
        if index is None:
            self.invalidate()
            return
        bar = self.terminal.verticalScrollBar()
        if not bar.value() <= index < bar.value() + screen.rows:
            bar.setValue(max(0, index - screen.rows // 2))

    def shutdown(self):
        self._timer.stop()
        self._batch.stop()
        self._lines = ()
        self.matches = []
        self.highlights = {}
        self._text, self._positions = [], []
