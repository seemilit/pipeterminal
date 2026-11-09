"""Bounded terminal metadata cache and read-only directory-cache lookup."""

import posixpath
import time
from collections import OrderedDict

from ..listing import listing_operand
from ..navigation import match_listed_path


class TerminalEntryCache:
    def __init__(self, limit=256):
        self.limit = limit
        self._connection = None
        self._entries = OrderedDict()
        self._updated = {}

    def bind(self, connection):
        token = (connection.transport, connection.connection_stop) if connection is not None else None
        if token != self._connection:
            self._connection = token
            self._entries.clear()
            self._updated.clear()

    def key(self, reference, cwd):
        return (cwd, reference.context_id, reference.text, reference.prompt,
                reference.output, reference.offset, reference.command)

    def get(self, key):
        entry = self._entries.get(key)
        if key in self._entries:
            self._entries.move_to_end(key)
        return entry

    def __contains__(self, key):
        return key in self._entries

    def is_fresh(self, key):
        return key in self._entries and time.monotonic() - self._updated.get(key, 0) < 2

    def put(self, key, entry):
        self._entries[key] = entry
        self._updated[key] = time.monotonic()
        self._entries.move_to_end(key)
        while len(self._entries) > self.limit:
            removed, _entry = self._entries.popitem(last=False)
            self._updated.pop(removed, None)

    def invalidate(self, directories):
        for key, entry in tuple(self._entries.items()):
            if entry is None or any(entry.path == path or entry.path.startswith(path.rstrip("/") + "/") for path in directories):
                self._entries.pop(key, None)
                self._updated.pop(key, None)


def cached_path_entry(reference, cwd, lookup):
    value = reference.text
    if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None

    def find(path):
        # Do not normalize .. across a possibly symbolic directory.
        if not path.startswith("/") or ".." in path.split("/"):
            return None
        path = path.rstrip("/") or "/"
        entries = lookup(posixpath.dirname(path) or "/")
        if entries is None:
            return None
        return next((entry for entry in entries if entry.path == path and not entry.link), None)

    if reference.prompt and cwd is not None:
        return find(cwd)
    if value.startswith("/"):
        return find(value)
    if cwd is None or value == "~" or value.startswith("~/"):
        return None
    try:
        operand, children = listing_operand(reference.command)
    except ValueError:
        return None
    directory = cwd
    if operand is not None and children:
        if operand == "~" or operand.startswith("~/"):
            return None
        target = operand if operand.startswith("/") else posixpath.join(cwd, operand)
        if ".." in target.split("/"):
            return None
        target = posixpath.normpath(target)
        target_entry = find(target)
        if lookup(target) is not None or (target_entry is not None and target_entry.directory):
            directory = target
        elif target_entry is not None and "/" not in value.rstrip("/"):
            directory = posixpath.dirname(target)
        else:
            return None
    entries = lookup(directory)
    if entries is not None and reference.output and "/" not in value.rstrip("/"):
        matched = match_listed_path((entry.name for entry in entries), reference, directory)
        if matched is not None:
            return find(matched)
        return None
    return find(posixpath.join(directory, value))
