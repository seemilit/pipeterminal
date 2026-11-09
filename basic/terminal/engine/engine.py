"""Python terminal engine: bytes in, screen state and protocol responses out."""

from dataclasses import replace
from itertools import count
from wcwidth import wcwidth, wcswidth

from .buffer import ScreenBuffer
from .model import Cell, Cursor, Line
from .parser import ANSIParser
from ..paths import cell_text, prompt_match


_PROMPT_IDS = count()


class TerminalEngine:
    def __init__(self, rows: int = 24, cols: int = 80, history_limit: int = 5000) -> None:
        self.screen = ScreenBuffer(rows, cols, history_limit)
        self.cursor = Cursor()
        self.attributes = Cell()
        self._parser = ANSIParser(self)
        self._saved_cursor = Cursor()
        self._normal_screen: tuple[ScreenBuffer, Cursor] | None = None
        self._last_printed: tuple[Line, int] | None = None
        self._wrap_pending = False
        self.autowrap = True
        self.application_cursor = False
        self.bracketed_paste = False
        self._origin = False
        self._top, self._bottom = 0, self.screen.rows - 1
        self._responses: list[bytes] = []
        self._events: list[tuple[str, str]] = []
        self._charset = False
        self._path_context = None
        self._last_prompt = None
        self._input_mode = False
        self._queued_echo_lines = 0
        self._prompt_identity = None
        self._path_enabled = True

    @property
    def shell_ready(self) -> bool:
        if self._normal_screen is not None:
            return False
        line = self.screen.lines[self.cursor.row]
        return (
            line.path_enabled and line.prompt_context == self._path_context and line.input_start is not None
            and not any(cell.text.strip() for cell in line.cells[line.input_start:])
        )

    @property
    def path_links_enabled(self) -> bool:
        return self._normal_screen is None

    def feed(self, data: bytes) -> None:
        previous = self.screen.lines[self.cursor.row]
        self.screen.touch(previous)
        self._parser.feed(data)
        self.screen.touch(self.screen.lines[self.cursor.row])

    def note_input(self, data: bytes) -> None:
        if self._input_mode and self._normal_screen is None:
            data = data.removeprefix(b"\x1b[200~").removesuffix(b"\x1b[201~")
            data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            extra = data.count(b"\n") - int(data.endswith(b"\n"))
            self._queued_echo_lines += max(0, extra)

    def finish(self) -> None:
        self._parser.feed(b"", final=True)

    def reset(self) -> None:
        self.__init__(self.screen.rows, self.screen.cols, self.screen.history.maxlen or 0)

    def resize(self, rows: int, cols: int) -> None:
        self.cursor.row = self.screen.resize(rows, cols, self.cursor.row)
        self.cursor.col = min(self.cursor.col, self.screen.cols - 1)
        self._top, self._bottom = 0, self.screen.rows - 1
        self._wrap_pending = False
        self._last_printed = None

    def take_responses(self) -> bytes:
        result = b"".join(self._responses)
        self._responses.clear()
        return result

    def take_events(self) -> list[tuple[str, str]]:
        events, self._events = self._events, []
        return events

    def _move(self, row: int, col: int) -> None:
        self.cursor.row = max(0, min(self.screen.rows - 1, row))
        self.cursor.col = max(0, min(self.screen.cols - 1, col))
        self._wrap_pending = False
        self._last_printed = None

    def _linefeed(self) -> None:
        if self.cursor.row == self._bottom:
            self.screen.scroll_up(self._top, self._bottom, attributes=self.attributes)
        else:
            self.cursor.row = min(self.screen.rows - 1, self.cursor.row + 1)
        self._wrap_pending = False

    def draw(self, char: str) -> None:
        if self._charset:
            char = dict(zip("jklmnqtuvwx", "┘┐┌└┼─├┤┴┬│")).get(char, char)
        width = wcwidth(char)
        if self._last_printed is not None:
            line, col = self._last_printed
            previous = line.cells[col]
            regional = 0x1F1E6 <= ord(char) <= 0x1F1FF
            previous_regional = len(previous.text) == 1 and 0x1F1E6 <= ord(previous.text) <= 0x1F1FF
            if width == 0 or previous.text.endswith("\u200d") or (regional and previous_regional) or 0x1F3FB <= ord(char) <= 0x1F3FF:
                text = previous.text + char
                new_width = 2 if regional and previous_regional else max(1, min(2, wcswidth(text)))
                if new_width == 2 and col + 1 >= len(line.cells):
                    new_width = previous.width
                if new_width > previous.width:
                    self.screen.clear_cluster(line, col + 1)
                    line.cells[col + 1] = replace(previous, text="", width=0)
                elif new_width < previous.width:
                    line.cells[col + 1] = Cell()
                line.cells[col] = replace(previous, text=text, width=new_width)
                if line is self.screen.lines[self.cursor.row]:
                    position = col + new_width
                    self.cursor.col = min(self.screen.cols - 1, position)
                    self._wrap_pending = position >= self.screen.cols
                self.screen.touch(line)
                return
        if width <= 0:
            return
        width = min(2, width)
        if self._wrap_pending or self.cursor.col + width > self.screen.cols:
            if self.autowrap:
                self.screen.lines[self.cursor.row].wrapped = True
                self._linefeed()
                self.cursor.col = 0
            else:
                self.cursor.col = self.screen.cols - width
        row, col = self.cursor.row, self.cursor.col
        line = self.screen.lines[row]
        line.path_enabled = self._path_enabled
        self.screen.put(row, col, replace(
            self.attributes, text=char, width=width, input=self._input_mode,
            context_id=self._path_context,
        ))
        if char in "#$" and self._normal_screen is None:
            text, positions = cell_text(line)
            prompt = prompt_match(text[:sum(len(cell.text) for cell in line.cells[:col + width] if not cell.continuation)])
            if prompt is not None:
                identity, directory, (start, end), _ = prompt
                if self._prompt_identity is None:
                    self._prompt_identity = identity
                self._path_enabled = line.path_enabled = identity == self._prompt_identity
                line.prompt_path = (positions[start][1], positions[end - 1][2])
                line.prompt_directory = directory
                line.input_start = col + width
                marker = (line.id, identity, directory)
                if marker != self._last_prompt:
                    self._path_context = next(_PROMPT_IDS)
                    self._last_prompt = marker
                line.prompt_context = self._path_context
                self._input_mode = True
                # A later redraw in the same feed may replace this line's
                # prompt. Keep the metadata as it was at this stream position.
                self._events.append(("prompt", f"{self._path_context};{line.id};{int(line.path_enabled)};{directory}"))
        self._last_printed = (self.screen.lines[row], col)
        position = col + width
        self.cursor.col = min(self.screen.cols - 1, position)
        self._wrap_pending = position >= self.screen.cols

    def _command_input(self) -> str | None:
        last = len(self.screen.history) + self.cursor.row
        first = last
        while first > 0 and self.screen.row_at(first - 1).wrapped:
            first -= 1
            if last - first >= 64:
                return None
        prompt = self.screen.row_at(first)
        if prompt.input_start is None or not prompt.path_enabled:
            return None
        parts = []
        for index in range(first, last + 1):
            line = self.screen.row_at(index)
            start = prompt.input_start if index == first else 0
            end = len(line.cells)
            while end > start and line.cells[end - 1].text == " " and line.cells[end - 1].context_id is None:
                end -= 1
            parts.append("".join(cell.text for cell in line.cells[start:end] if not cell.continuation))
        text = "".join(parts)
        return text if len(text) <= 8192 else None

    def control(self, char: str) -> None:
        self._last_printed = None
        if char in "\n\v\f":
            if char == "\n" and self._input_mode and self._normal_screen is None:
                command = self._command_input()
                self._events.append(("command_input" if command is not None else "command_input_unknown", command or ""))
            self._linefeed()
            if self._input_mode and self._queued_echo_lines:
                self._queued_echo_lines -= 1
            else:
                self._input_mode = False
            self._last_prompt = None
        elif char == "\r":
            self._move(self.cursor.row, 0)
        elif char == "\b":
            self._move(self.cursor.row, self.cursor.col - 1)
        elif char == "\t":
            self._move(self.cursor.row, min(self.screen.cols - 1, (self.cursor.col // 8 + 1) * 8))

    def charset(self, char: str) -> None:
        self._charset = char == "0"

    def escape(self, char: str) -> None:
        self._last_printed = None
        if char == "7":
            self._saved_cursor = replace(self.cursor)
        elif char == "8":
            self._move(self._saved_cursor.row, self._saved_cursor.col)
        elif char in "DE":
            self._linefeed()
            if char == "E":
                self.cursor.col = 0
        elif char == "M":
            if self.cursor.row == self._top:
                self.screen.scroll_down(self._top, self._bottom, attributes=self.attributes)
            else:
                self.cursor.row = max(0, self.cursor.row - 1)
        elif char == "c":
            self.__init__(self.screen.rows, self.screen.cols, self.screen.history.maxlen or 0)

    def osc(self, data: str) -> None:
        self._events.append(("osc", data))

    def csi(self, sequence: str, command: str) -> None:
        private = sequence.startswith("?")
        prefix = sequence[:1] if sequence[:1] in "?>!" else ""
        raw = sequence.lstrip("?>!").rstrip(" ")
        try:
            values = [int(value or "0") for value in raw.split(";")]
        except ValueError:
            return
        value = values[0] if values else 0
        amount = max(1, value)
        row, col = self.cursor.row, self.cursor.col
        if command == "m":
            self._sgr(values)
            return
        self._last_printed = None
        if command in "ABCD":
            dr, dc = {"A": (-amount, 0), "B": (amount, 0), "C": (0, amount), "D": (0, -amount)}[command]
            self._move(row + dr, col + dc)
        elif command in "EF":
            self._move(row + (amount if command == "E" else -amount), 0)
        elif command in "G`":
            self._move(row, amount - 1)
        elif command in "Hf":
            target_row = max(1, value) - 1 + (self._top if self._origin else 0)
            self._move(min(self._bottom, target_row) if self._origin else target_row, max(1, values[1] if len(values) > 1 else 1) - 1)
        elif command == "d":
            self._move(amount - 1, col)
        elif command == "J":
            if value == 3:
                self.screen.history.clear()
                self.screen._history_changed = True
            elif value == 2:
                for index in range(self.screen.rows):
                    self.screen.erase(index, 0, self.screen.cols, self.attributes)
            elif value == 0:
                self.screen.erase(row, col, self.screen.cols, self.attributes)
                for index in range(row + 1, self.screen.rows):
                    self.screen.erase(index, 0, self.screen.cols, self.attributes)
            elif value == 1:
                for index in range(row):
                    self.screen.erase(index, 0, self.screen.cols, self.attributes)
                self.screen.erase(row, 0, col + 1, self.attributes)
        elif command == "K":
            left, right = (col, self.screen.cols) if value == 0 else (0, col + 1) if value == 1 else (0, self.screen.cols)
            self.screen.erase(row, left, right, self.attributes)
        elif command == "X":
            self.screen.erase(row, col, min(self.screen.cols, col + amount), self.attributes)
        elif command in "@P":
            line = self.screen.lines[row]
            if line.cells[col].continuation:
                self.screen.clear_cluster(line, col)
            blanks = [replace(self.attributes, text=" ", width=1)] * min(amount, self.screen.cols - col)
            if command == "@":
                line.cells[col:col] = blanks
                line.cells = line.cells[:self.screen.cols]
            else:
                del line.cells[col:col + len(blanks)]
                line.cells.extend(blanks)
            self.screen.normalize(line)
        elif command in "LM" and self._top <= row <= self._bottom:
            method = self.screen.scroll_down if command == "L" else self.screen.scroll_up
            method(row, self._bottom, amount, self.attributes)
        elif command in "ST":
            method = self.screen.scroll_up if command == "S" else self.screen.scroll_down
            method(self._top, self._bottom, amount, self.attributes)
        elif command == "r" and not prefix:
            top, bottom = max(1, value) - 1, (values[1] or self.screen.rows) - 1 if len(values) > 1 else self.screen.rows - 1
            if 0 <= top < bottom < self.screen.rows:
                self._top, self._bottom = top, bottom
                self._move(top if self._origin else 0, 0)
        elif command == "s":
            self._saved_cursor = replace(self.cursor)
        elif command == "u":
            self._move(self._saved_cursor.row, self._saved_cursor.col)
        elif command == "n" and not prefix:
            if value == 6:
                self._responses.append(f"\x1b[{row + 1};{col + 1}R".encode("ascii"))
            elif value == 5:
                self._responses.append(b"\x1b[0n")
        elif command == "c":
            self._responses.append(b"\x1b[>0;1;0c" if prefix == ">" else b"\x1b[?1;0c")
        elif command in "hl" and private:
            for mode in values:
                self._set_mode(mode, command == "h")

    def _set_mode(self, mode: int, enabled: bool) -> None:
        if mode == 25:
            self.cursor.visible = enabled
        elif mode == 7:
            self.autowrap = enabled
        elif mode == 1:
            self.application_cursor = enabled
        elif mode == 6:
            self._origin = enabled
            self._move(self._top if enabled else 0, 0)
        elif mode == 2004:
            self.bracketed_paste = enabled
        elif mode in {47, 1047, 1049}:
            if enabled and self._normal_screen is None:
                self._normal_screen = (self.screen, replace(self.cursor))
                self.screen = ScreenBuffer(self.screen.rows, self.screen.cols, 0)
                self.cursor = Cursor()
            elif not enabled and self._normal_screen is not None:
                rows, cols = self.screen.rows, self.screen.cols
                self.screen, self.cursor = self._normal_screen
                self._normal_screen = None
                self.resize(rows, cols)
                self.screen.invalidate()
            self._top, self._bottom = 0, self.screen.rows - 1
            self._wrap_pending = False

    def _sgr(self, values: list[int]) -> None:
        index = 0
        while index < len(values):
            code = values[index]
            if code == 0:
                self.attributes = Cell()
            elif code in {1, 3, 4, 7, 22, 23, 24, 27}:
                field, enabled = {1: ("bold", True), 3: ("italic", True), 4: ("underline", True), 7: ("inverse", True), 22: ("bold", False), 23: ("italic", False), 24: ("underline", False), 27: ("inverse", False)}[code]
                self.attributes = replace(self.attributes, **{field: enabled})
            elif 30 <= code <= 37 or 90 <= code <= 97:
                self.attributes = replace(self.attributes, foreground=code - 30 if code < 90 else code - 90 + 8)
            elif 40 <= code <= 47 or 100 <= code <= 107:
                self.attributes = replace(self.attributes, background=code - 40 if code < 100 else code - 100 + 8)
            elif code in {39, 49}:
                self.attributes = replace(self.attributes, **{"foreground" if code == 39 else "background": None})
            elif code in {38, 48} and index + 2 < len(values):
                color = None
                if values[index + 1] == 5:
                    color = max(0, min(255, values[index + 2]))
                    index += 2
                elif values[index + 1] == 2 and index + 4 < len(values):
                    color = tuple(max(0, min(255, component)) for component in values[index + 2:index + 5])
                    index += 4
                if color is not None:
                    self.attributes = replace(self.attributes, **{"foreground" if code == 38 else "background": color})
            index += 1
