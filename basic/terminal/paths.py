"""Qt-free path hit testing using terminal cells, including wide characters."""

import re
import shlex
from dataclasses import dataclass


_PROMPT = re.compile(r"^(?:\([^\n]*\)\s*)?(?:\[(?P<bracket_user>[^\s@\]]+@[^\s\]]+)\s+(?P<bracket_path>[^\]]+)\]|(?P<user>[^\s@:]+@[^\s:]+):(?P<path>[^#$]+))[#$]\s*$")
_TOKEN = re.compile(r'''(?:'[^']*'|"(?:\\.|[^"\\])*"|\\.|[^\s'"\\<>|;&])+''')


@dataclass(frozen=True)
class PathReference:
    text: str
    context_id: int | None
    spans: tuple[tuple[int, int, int], ...]
    prompt: bool = False
    output: str = ""
    offset: int = 0
    command: str | None = None


def prompt_match(text: str):
    match = _PROMPT.fullmatch(text)
    if match is None:
        return None
    field = "bracket_path" if match.group("bracket_path") is not None else "path"
    identity = match.group("bracket_user") or match.group("user")
    return identity, match.group(field), match.span(field), match.end()


def input_reference_at(text: str, offset: int) -> PathReference | None:
    if text and offset == len(text):
        offset -= 1
    for match in _TOKEN.finditer(text):
        if match.start() <= offset < match.end():
            try:
                value = shlex.split(match.group())[0]
            except (ValueError, IndexError):
                return None
            if value and "://" not in value:
                return PathReference(value, None, (), output=text, offset=match.start())
    return None


def cell_text(line, trim_padding: bool = False):
    text, positions = [], []
    end = len(line.cells)
    if trim_padding:
        while end and line.cells[end - 1].text == " " and line.cells[end - 1].context_id is None:
            end -= 1
    for col, cell in enumerate(line.cells[:end]):
        if not cell.continuation:
            text.append(cell.text)
            positions.extend([(line.id, col, col + cell.width)] * len(cell.text))
    return "".join(text), positions


def reference_at(screen, line_id: int, col: int) -> PathReference | None:
    index = screen.index_of(line_id)
    if index is None:
        return None
    line = screen.row_at(index)
    if not line.path_enabled:
        return None
    text, positions = cell_text(line)
    if line.prompt_path is not None:
        start, end = line.prompt_path
        if start <= col < end:
            return PathReference(line.prompt_directory, line.prompt_context, ((line.id, start, end),), True)
        return None
    if line.cells[col].input:
        return None
    # Join physical rows only where the engine recorded automatic wrapping.
    first, last = index, index
    while first > 0 and index - first < 8 and screen.row_at(first - 1).wrapped:
        first -= 1
    limit = len(screen.history) + screen.rows
    while last + 1 < limit and last - index < 8 and screen.row_at(last).wrapped:
        last += 1
    text, positions, cells = "", [], {}
    for row in range(first, last + 1):
        current = screen.row_at(row)
        part, offsets = cell_text(current, trim_padding=True)
        text += part
        positions.extend(offsets)
        cells[current.id] = current
    offset = next((i for i, position in enumerate(positions) if position[0] == line_id and position[1] == col), None)
    if offset is None:
        return None
    # pwd prints a complete absolute path, possibly containing spaces or
    # punctuation. Treat that output as one path rather than shell tokens.
    absolute = text
    if absolute.startswith("/") and not re.search(r"\s{2,}\S", absolute) and offset < len(absolute):
        spans = _output_spans(positions[:len(absolute)], cells)
        if spans is not None:
            return PathReference(absolute, line.cells[col].context_id, spans, output=text)
    for match in _TOKEN.finditer(text):
        if not match.start() <= offset < match.end():
            continue
        raw = match.group()
        try:
            value = shlex.split(raw)[0]
        except (ValueError, IndexError):
            return None
        if not value or "://" in value:
            return None
        spans = _output_spans(positions[match.start():match.end()], cells)
        if spans is not None:
            return PathReference(value, line.cells[col].context_id, spans, output=text, offset=match.start())
    return None


def _output_spans(positions, lines):
    spans = []
    for identifier, left, right in positions:
        line = lines[identifier]
        if line.cells[left].input or not line.path_enabled:
            return None
        if spans and spans[-1][0] == identifier:
            spans[-1] = (identifier, spans[-1][1], right)
        else:
            spans.append((identifier, left, right))
    return tuple(spans)
