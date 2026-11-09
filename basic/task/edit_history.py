"""Serialized undo snapshots bounded by both count and memory."""
import json
from sys import getsizeof
from time import monotonic


class EditHistory:
    MAX_ENTRIES = 50
    MAX_BYTES = 32 * 1024 * 1024

    def __init__(self):
        self.reset()

    def reset(self):
        self.undo_stack, self.redo_stack = [], []
        self._key, self._time = None, 0
        self.limited = False

    def _snapshot(self, document):
        chunks, size = [], 0
        encoder = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"))
        for text in encoder.iterencode(document):
            chunk = text.encode("utf-8")
            size += len(chunk)
            if size + getsizeof(b"") > self.MAX_BYTES:
                return None
            chunks.append(chunk)
        return b"".join(chunks)

    def _trim(self, preferred):
        other = self.redo_stack if preferred is self.undo_stack else self.undo_stack
        while len(preferred) > self.MAX_ENTRIES:
            del preferred[0]
        while sum(getsizeof(item) for item in self.undo_stack + self.redo_stack) > self.MAX_BYTES:
            if other:
                del other[0]
            elif preferred:
                del preferred[0]
            else:
                break

    def remember(self, document, key=None):
        now = monotonic()
        coalesced = key is not None and key == self._key and now - self._time <= 0.8 and not self.limited
        self.redo_stack.clear()
        if not coalesced:
            snapshot = self._snapshot(document)
            if snapshot is None:
                self.reset()
                self.limited = True
                return False
            self.undo_stack.append(snapshot)
            self._trim(self.undo_stack)
        self._key, self._time = key, now
        self.limited = False
        return True

    def restore(self, document, redo=False):
        source, target = (self.redo_stack, self.undo_stack) if redo else (self.undo_stack, self.redo_stack)
        if not source:
            return None
        snapshot = source.pop()
        current = self._snapshot(document)
        self.limited = current is None
        if current is not None:
            target.append(current)
            self._trim(target)
        else:
            target.clear()
        self._key = None
        return json.loads(snapshot)
