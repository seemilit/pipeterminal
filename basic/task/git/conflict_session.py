"""In-memory merge drafts, explicit conflict decisions and text-only undo history."""

import re
from copy import deepcopy
from dataclasses import dataclass, field


BLOCK = re.compile(r"^([<]{7,})[^\n]*\n(.*?)^[=]{7,}\r?\n(.*?)^[>]{7,}[^\n]*(?:\n|$)", re.MULTILINE | re.DOTALL)
BASE = re.compile(r"^[|]{7,}[^\n]*\n", re.MULTILINE)
MARKER = re.compile(r"^(?:<{7,}|={7,}|>{7,}|[|]{7,})(?:[^\n]*)$", re.MULTILINE)


@dataclass
class ConflictBlock:
    start: int
    end: int
    left: str
    right: str
    base: str = ""
    state: str = "unresolved"
    ignored: set = field(default_factory=set)
    accepted: list = field(default_factory=list)


class FileMerge:
    def __init__(self, item):
        self.item = item
        self.blocks = []
        original = item.get("result", item["stages"].get(2, {}).get("text", ""))
        original = original.replace("\r\n", "\n").replace("\r", "\n")
        parts, offset, length = [], 0, 0
        for match in BLOCK.finditer(original) if item["text"] else ():
            prefix = original[offset:match.start()]
            parts.append(prefix)
            length += len(prefix)
            left, right = match.group(2), match.group(3)
            ancestor = BASE.search(left)
            base = left[ancestor.end():] if ancestor else ""
            if ancestor:
                left = left[:ancestor.start()]
            initial = base if ancestor else left
            self.blocks.append(ConflictBlock(length, length + len(initial), left, right, base))
            parts.append(initial)
            length += len(initial)
            offset = match.end()
        parts.append(original[offset:])
        self.text = "".join(parts) if item["text"] else ""
        self.resolution = None
        self.history = []
        self.history_index = -1
        self.record()
        self._initial = deepcopy(self.history[0])

    @property
    def remaining(self):
        return sum(block.state in {"unresolved", "edited"} for block in self.blocks)

    def record(self):
        snapshot = (self.text, deepcopy(self.blocks), self.resolution)
        if self.history_index >= 0 and self.history[self.history_index] == snapshot:
            return
        del self.history[self.history_index + 1:]
        self.history.append(snapshot)
        # Keep bounded, per-file history; formatting never enters this history.
        while len(self.history) > 100 or (len(self.history) > 1 and sum(len(entry[0]) * 4 for entry in self.history) > 32 * 1024 * 1024):
            self.history.pop(0)
        self.history_index = len(self.history) - 1

    def restore(self, direction):
        target = self.history_index + direction
        if not 0 <= target < len(self.history):
            return False
        self.history_index = target
        self.text, self.blocks, self.resolution = deepcopy(self.history[target])
        return True

    def edit(self, text):
        if self.text == text:
            return
        old = self.text
        start = 0
        while start < min(len(old), len(text)) and old[start] == text[start]:
            start += 1
        end, new_end = len(old), len(text)
        while end > start and new_end > start and old[end - 1] == text[new_end - 1]:
            end -= 1
            new_end -= 1
        self.replace(start, end, text[start:new_end], manual=True)
        self.record()

    def replace(self, start, end, value, manual=False, selected=None):
        delta = len(value) - (end - start)
        selected_index = next((index for index, block in enumerate(self.blocks) if block is selected), -1)
        for index, block in enumerate(self.blocks):
            if block is selected:
                block.start, block.end = start, start + len(value)
            elif selected is not None and block.end <= start and index < selected_index:
                continue
            elif block.start >= end and (selected is not None or not (start == end and block.start == start)):
                block.start += delta
                block.end += delta
            elif block.end > start or (block.start == block.end == start):
                block.start = min(block.start, start)
                block.end = max(block.start, block.end + delta if block.end >= end else start + len(value))
                if manual:
                    block.state = "edited"
                    block.ignored.clear()
                    block.accepted.clear()
        self.text = self.text[:start] + value + self.text[end:]
        self.resolution = None

    def choose(self, index, choice):
        block = self.blocks[index]
        values = {"left": block.left, "right": block.right, "both": block.left + block.right, "reverse": block.right + block.left}
        self.replace(block.start, block.end, values[choice], selected=block)
        block.state = choice
        block.ignored = {"right" if choice == "left" else "left"} if choice in {"left", "right"} else set()
        block.accepted = [choice] if choice in {"left", "right"} else (["left", "right"] if choice == "both" else ["right", "left"])
        self.record()

    def accept_side(self, index, side):
        block = self.blocks[index]
        block.ignored.discard(side)
        if side not in block.accepted:
            block.accepted.append(side)
        self._side_decision(block)

    def ignore(self, index, side):
        block = self.blocks[index]
        block.ignored.add(side)
        if side in block.accepted:
            block.accepted.remove(side)
        self._side_decision(block)

    def _side_decision(self, block):
        value = "".join(getattr(block, side) for side in block.accepted) if block.accepted else block.base
        self.replace(block.start, block.end, value, selected=block)
        decided = set(block.accepted) | block.ignored
        if len(decided) < 2:
            block.state = "unresolved"
        elif not block.accepted:
            block.state = "base"
        elif len(block.accepted) == 1:
            block.state = block.accepted[0]
        else:
            block.state = "both" if block.accepted[0] == "left" else "reverse"
        self.record()

    def reset(self):
        self.text, self.blocks, self.resolution = deepcopy(self._initial)
        self.record()

    def can_choose(self, index):
        current = self.blocks[index]
        return not any(other is not current and max(current.start, other.start) < min(current.end, other.end) for other in self.blocks)

    def mark_manual(self, index):
        current = self.blocks[index]
        for block in self.blocks:
            if block is current or max(current.start, block.start) < min(current.end, block.end):
                block.state = "manual"
        self.resolution = None
        self.record()

    def choose_file(self, choice):
        stage = self.item["stages"].get(2 if choice == "left" else 3)
        self.text = stage.get("text", "").replace("\r\n", "\n").replace("\r", "\n") if stage else ""
        # Whole-file selection supersedes the old block positions.
        self.blocks = []
        self.resolution = (choice, None)
        self.record()

    def apply(self):
        if self.resolution is not None:
            return True
        if not self.item["text"] or self.remaining or MARKER.search(self.text):
            return False
        self.resolution = ("text", self.text)
        self.record()
        return True


class ConflictSession:
    def __init__(self, request):
        self.request = request
        self.files = request.get("drafts")
        if self.files is None:
            self.files = {item["path"]: FileMerge(item) for item in request["files"]}

    @property
    def resolutions(self):
        return {path: draft.resolution for path, draft in self.files.items() if draft.resolution is not None}
