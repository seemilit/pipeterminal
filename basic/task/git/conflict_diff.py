"""Background comparison and editor decorations shared by the merge view."""

import re
from difflib import SequenceMatcher
from PySide6.QtGui import QColor, QTextCursor, QTextFormat
from PySide6.QtWidgets import QTextEdit


class ConflictDiff:
    def _build_maps(self, revision, texts, base, mode="word", ignore_space=False):
        maps = {}
        decorations = [[], [], []]
        normalize = lambda lines: [re.sub(r"\s+", "", line) for line in lines] if ignore_space else lines
        compared = [normalize(lines) for lines in texts]
        try:
            for pane, lines in enumerate(texts):
                for tag, a0, a1, b0, b1 in SequenceMatcher(None, normalize(base), compared[pane], autojunk=True).get_opcodes():
                    if tag == "equal":
                        continue
                    color = "insert" if tag == "insert" else "delete" if tag == "delete" else "replace"
                    for line in range(b0, max(b0 + 1, b1)):
                        decorations[pane].append((line, None, None, color))
                    if tag == "replace" and mode == "word":
                        for old, new in zip(range(a0, min(a1, a0 + 500)), range(b0, b1)):
                            if max(len(base[old]), len(lines[new])) > 4000:
                                continue
                            old_tokens = list(re.finditer(r"\s+|\w+|[^\w\s]", base[old]))
                            new_tokens = list(re.finditer(r"\s+|\w+|[^\w\s]", lines[new]))
                            if ignore_space:
                                old_tokens = [token for token in old_tokens if not token.group().isspace()]
                                new_tokens = [token for token in new_tokens if not token.group().isspace()]
                            for operation, _a, _b, start, end in SequenceMatcher(None, [token.group() for token in old_tokens], [token.group() for token in new_tokens], autojunk=False).get_opcodes():
                                if operation != "equal" and end > start:
                                    decorations[pane].append((new, new_tokens[start].start(), new_tokens[end - 1].end(), "character"))
            for side in (0, 2):
                opcodes = SequenceMatcher(None, compared[1], compared[side], autojunk=True).get_opcodes()
                forward = [(a0, a1, b0, b1) for _tag, a0, a1, b0, b1 in opcodes]
                backward = [(b0, b1, a0, a1) for a0, a1, b0, b1 in forward]
                maps[(1, side)] = ([entry[0] for entry in forward], forward)
                maps[(side, 1)] = ([entry[0] for entry in backward], backward)
        except Exception:
            maps = {}
        try:
            self.mapping_ready.emit(revision, (maps, decorations))
        except RuntimeError:
            pass  # Dialog may have been closed while the worker finishes.

    def _selections(self, editor, decorations):
        colors = {"insert": QColor(60, 190, 100, 45), "delete": QColor(230, 80, 80, 55), "replace": QColor(70, 140, 240, 45), "character": QColor(240, 170, 40, 110), "conflict": QColor(230, 80, 80, 65)}
        selections = []
        for line, start, end, color in decorations:
            block = editor.document().findBlockByNumber(line)
            if not block.isValid():
                continue
            cursor = QTextCursor(block)
            selection = QTextEdit.ExtraSelection()
            if start is None:
                selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            else:
                value = block.text()
                cursor.setPosition(block.position() + len(value[:start].encode("utf-16-le")) // 2)
                cursor.setPosition(block.position() + len(value[:end].encode("utf-16-le")) // 2, QTextCursor.MoveMode.KeepAnchor)
            selection.cursor = cursor
            selection.format.setBackground(colors[color])
            selections.append(selection)
        return selections

