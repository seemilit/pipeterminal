"""Read-only path verification and immutable directory data for worker use."""

import posixpath
import shlex
import stat
from dataclasses import dataclass

from common.i18n import tr

from .backend import check_cancelled, open_sftp, read_directory
from .model import RemoteEntry
from .listing import hovered_names, listing_operand


@dataclass(frozen=True)
class DirectorySnapshot:
    directory: str
    entries: tuple
    selected_file: str | None = None


def read_shell_directory(context, cancel, pid, hint: str) -> str | None:
    with open_sftp(context, cancel) as sftp:
        home = sftp.normalize(".")
        try:
            cwd = sftp.readlink(f"/proc/{pid}/cwd") if pid is not None else None
        except OSError:
            cwd = None
        check_cancelled(context, cancel)
        expected = (
            posixpath.join(home, hint[2:] if hint != "~" else "")
            if hint == "~" or hint.startswith("~/") else hint if hint.startswith("/") else None
        )
        if cwd and cwd.startswith("/") and (
            (expected is not None and posixpath.normpath(cwd) == posixpath.normpath(expected))
            or (expected is None and posixpath.basename(cwd.rstrip("/")) == hint)
        ):
            return cwd
        # Full paths and ~ are unambiguous even without Linux /proc support.
        return sftp.normalize(expected) if expected is not None else None


def read_path_snapshot(context, cancel, reference, cwd: str | None, *, listing_allowed=None) -> DirectorySnapshot:
    with open_sftp(context, cancel) as sftp:
        path = _reference_path(sftp, context, cancel, reference, cwd, listing_limit=50 if listing_allowed is not None else None)
        requested_path = path
        try:
            path = sftp.normalize(path)
            check_cancelled(context, cancel)
            mode = sftp.stat(path).st_mode or 0
            selected = None
            if stat.S_ISREG(mode):
                selected, path = path, posixpath.dirname(path) or "/"
            elif not stat.S_ISDIR(mode):
                raise ValueError(tr("目标不是目录或普通文件"))
            if listing_allowed is not None and (not listing_allowed(requested_path) or not listing_allowed(path)):
                return DirectorySnapshot(requested_path if not listing_allowed(requested_path) else path, (), selected)
            directory, entries = read_directory(sftp, context, cancel, path)
        except FileNotFoundError as exc:
            raise FileNotFoundError(exc.errno, exc.strerror, path) from exc
        return DirectorySnapshot(directory, tuple(entries), selected)


def _reference_path(sftp, context, cancel, reference, cwd, *, listing_limit=None):
    value = reference.text
    if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(tr("服务器目录无效"))
    if reference.prompt and cwd is not None:
        return cwd
    if value == "~" or value.startswith("~/"):
        return posixpath.join(sftp.normalize("."), value[2:] if value != "~" else "")
    if value.startswith("/"):
        return value
    if cwd is not None:
        operand, children = listing_operand(reference.command)
        directory = cwd
        if operand is not None and children:
            target = (
                posixpath.join(sftp.normalize("."), operand[2:] if operand != "~" else "")
                if operand == "~" or operand.startswith("~/")
                else operand if operand.startswith("/") else posixpath.join(cwd, operand)
            )
            check_cancelled(context, cancel)
            if stat.S_ISDIR(sftp.stat(target).st_mode or 0):
                directory = target
            elif "/" not in value.rstrip("/"):
                directory = posixpath.dirname(target)
        return _listed_path(sftp, context, cancel, reference, directory, limit=listing_limit) or posixpath.join(directory, value)
    raise ValueError(tr("尚未确认此处的工作目录，请稍后重试"))


def read_path_entry(context, cancel, reference, cwd: str | None) -> RemoteEntry:
    with open_sftp(context, cancel) as sftp:
        path = _reference_path(sftp, context, cancel, reference, cwd, listing_limit=50).rstrip("/") or "/"
        name = posixpath.basename(path)
        if name in {"", ".", ".."}:
            path = sftp.normalize(path)
        else:
            path = posixpath.join(sftp.normalize(posixpath.dirname(path)), name)
        check_cancelled(context, cancel)
        attributes = sftp.lstat(path)
        mode = attributes.st_mode or 0
        link = stat.S_ISLNK(mode)
        directory = stat.S_ISDIR(mode)
        if link:
            try:
                directory = stat.S_ISDIR(sftp.stat(path).st_mode or 0)
            except OSError:
                check_cancelled(context, cancel)
        elif not directory and not stat.S_ISREG(mode):
            raise ValueError(tr("目标不是目录或普通文件"))
        check_cancelled(context, cancel)
        return RemoteEntry(posixpath.basename(path) or "/", path, directory, link,
                           int(attributes.st_size or 0), int(attributes.st_mtime or 0), mode)


def _listed_path(sftp, context, cancel, reference, cwd: str, *, limit=None) -> str | None:
    value = reference.text
    if not reference.output or value in {".", ".."} or "/" in value.rstrip("/"):
        return None
    if limit is not None:
        entries = []
        iterator = sftp.listdir_iter(cwd, read_aheads=1)
        try:
            for entry in iterator:
                check_cancelled(context, cancel)
                entries.append(entry.filename)
                if len(entries) > limit:
                    break
        except OSError:
            check_cancelled(context, cancel)
            return None
        finally:
            close = getattr(iterator, "close", None)
            if close is not None:
                close()
        if len(entries) <= limit:
            return match_listed_path(entries, reference, cwd)
        for name in hovered_names(reference):
            check_cancelled(context, cancel)
            path = match_listed_path((name,), reference, cwd)
            if path is not None:
                try:
                    sftp.lstat(path)
                except FileNotFoundError:
                    continue
                return path
        raise ValueError(tr("无法确定输出目录，请使用完整路径"))
    def names():
        try:
            for entry in sftp.listdir_iter(cwd, read_aheads=4):
                check_cancelled(context, cancel)
                yield entry.filename
        except OSError:
            # Retain direct verification if listing is not permitted.
            check_cancelled(context, cancel)
    return match_listed_path(names(), reference, cwd)


def match_listed_path(names, reference, cwd: str) -> str | None:
    text, offset = reference.output, reference.offset
    matched = None
    length = 0
    for name in names:
        if not name or "/" in name or any(ord(char) < 32 or ord(char) == 127 for char in name):
            continue
        # Match complete names in columns, long listings and quoted or
        # escaped output. No command name or alias needs special handling.
        escaped = "".join("\\" + char if char.isspace() or char in "\\'\"" else char for char in name)
        quoted = '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'
        for display in {name, shlex.quote(name), escaped, quoted}:
            start = text.find(display)
            while start >= 0 and start <= offset:
                end = start + len(display)
                marked_end = end + int(end < len(text) and text[end] in "/@*|=")
                if (
                    start <= offset < marked_end
                    and (start == 0 or text[start - 1].isspace())
                    and (marked_end == len(text) or text[marked_end].isspace())
                    and len(name) > length
                ):
                    matched, length = posixpath.join(cwd, name), len(name)
                start = text.find(display, start + 1)
    return matched
