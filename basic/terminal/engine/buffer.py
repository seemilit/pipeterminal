"""A cell grid and bounded scrollback; no Qt or SSH dependencies."""

from collections import deque
from dataclasses import replace
from itertools import count

from .model import Cell, Damage, Line


_LINE_IDS = count()


class ScreenBuffer:
    def __init__(self, rows: int, cols: int, history_limit: int = 5000) -> None:
        self.rows, self.cols = max(1, rows), max(2, cols)
        self.history: deque[Line] = deque(maxlen=max(0, history_limit))
        self.lines = [self.blank_line() for _ in range(self.rows)]
        self._dirty: set[int] = set()
        self._full = True
        self._history_changed = True

    def blank_line(self, attributes: Cell = Cell()) -> Line:
        blank = replace(attributes, text=" ", width=1)
        return Line(next(_LINE_IDS), [blank] * self.cols)

    def touch(self, line: Line) -> None:
        self._dirty.add(line.id)

    def invalidate(self) -> None:
        self._full = True

    def take_damage(self) -> Damage:
        damage = Damage(frozenset(self._dirty), self._full, self._history_changed)
        self._dirty.clear()
        self._full = self._history_changed = False
        return damage

    def row_at(self, index: int) -> Line:
        if index < len(self.history):
            return self.history[index]
        return self.lines[index - len(self.history)]

    def index_of(self, line_id: int) -> int | None:
        for index, line in enumerate(self.history):
            if line.id == line_id:
                return index
        for index, line in enumerate(self.lines, start=len(self.history)):
            if line.id == line_id:
                return index
        return None

    def clear_cluster(self, line: Line, col: int, attributes: Cell = Cell()) -> None:
        if not 0 <= col < len(line.cells):
            return
        if line.cells[col].continuation and col > 0:
            col -= 1
        width = max(1, line.cells[col].width)
        line.cells[col:col + width] = [replace(attributes, text=" ", width=1)] * width
        self.touch(line)

    def put(self, row: int, col: int, cell: Cell) -> None:
        line = self.lines[row]
        if line.input_start is not None and col < line.input_start:
            line.prompt_path = line.input_start = None
            line.prompt_directory = ""
        for position in range(col, min(self.cols, col + cell.width)):
            self.clear_cluster(line, position, cell)
        line.cells[col] = cell
        if cell.width == 2 and col + 1 < self.cols:
            line.cells[col + 1] = replace(cell, text="", width=0)
        self.touch(line)

    def erase(self, row: int, start: int, end: int, attributes: Cell) -> None:
        line = self.lines[row]
        if line.input_start is not None and start < line.input_start and end > 0:
            line.prompt_path = line.input_start = None
            line.prompt_directory = ""
        for col in range(max(0, start), min(self.cols, end)):
            self.clear_cluster(line, col, attributes)
        self.touch(line)

    def scroll_up(self, top: int, bottom: int, amount: int = 1, attributes: Cell = Cell()) -> None:
        for _ in range(min(amount, bottom - top + 1)):
            removed = self.lines.pop(top)
            if top == 0 and bottom == self.rows - 1 and self.history.maxlen:
                self.history.append(removed)
                self._history_changed = True
            self.lines.insert(bottom, self.blank_line(attributes))
        for line in self.lines[top:bottom + 1]:
            self.touch(line)

    def scroll_down(self, top: int, bottom: int, amount: int = 1, attributes: Cell = Cell()) -> None:
        for _ in range(min(amount, bottom - top + 1)):
            self.lines.pop(bottom)
            self.lines.insert(top, self.blank_line(attributes))
        for line in self.lines[top:bottom + 1]:
            self.touch(line)

    def normalize(self, line: Line) -> None:
        for col, cell in enumerate(line.cells):
            if cell.width == 2:
                if col + 1 == len(line.cells) or not line.cells[col + 1].continuation:
                    line.cells[col] = Cell()
            elif cell.continuation and (col == 0 or line.cells[col - 1].width != 2):
                line.cells[col] = Cell()
        self.touch(line)

    def resize(self, rows: int, cols: int, cursor_row: int) -> int:
        rows, cols = max(1, rows), max(2, cols)
        remove_top = max(0, cursor_row - rows + 1)
        for _ in range(remove_top):
            removed = self.lines.pop(0)
            if self.history.maxlen:
                self.history.append(removed)
        self.lines = self.lines[:rows]
        self.rows, self.cols = rows, cols
        while len(self.lines) < rows:
            self.lines.append(self.blank_line())
        for line in self.lines:
            line.cells = (line.cells + [Cell()] * cols)[:cols]
            self.normalize(line)
        self._full = self._history_changed = True
        return max(0, cursor_row - remove_top)

    def selected_text(self, start: tuple[int, int], end: tuple[int, int]) -> str:
        if start > end:
            start, end = end, start
        start_index, end_index = self.index_of(start[0]), self.index_of(end[0])
        if start_index is None or end_index is None:
            return ""
        output: list[str] = []
        for index in range(start_index, end_index + 1):
            line = self.row_at(index)
            left = start[1] if index == start_index else 0
            right = end[1] + 1 if index == end_index else len(line.cells)
            if left < len(line.cells) and line.cells[left].continuation:
                left = max(0, left - 1)
            output.append("".join(cell.text for cell in line.cells[left:right] if not cell.continuation).rstrip())
            if index < end_index and not line.wrapped:
                output.append("\n")
        return "".join(output)
