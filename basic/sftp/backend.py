"""Worker-only SFTP I/O, recursive planning and temporary-file publication."""

import errno
import os
import posixpath
import stat
import sys
import time
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath
from threading import Event, Thread
from uuid import uuid4

from common.i18n import tr

from .model import PlannedEntry, RemoteEntry, TransferCancelled


def check_cancelled(context, cancel: Event) -> None:
    if cancel.is_set() or context.connection_stop.is_set() or not context.transport.is_active():
        raise TransferCancelled()


def _watch_channel(context, cancel: Event, finished: Event, initialized: Event, channel) -> None:
    deadline = time.monotonic() + 15
    while not finished.wait(0.1):
        if (
            cancel.is_set() or context.connection_stop.is_set() or not context.transport.is_active()
            or (not initialized.is_set() and time.monotonic() >= deadline)
        ):
            channel.close()
            return


@contextmanager
def open_sftp(context, cancel: Event):
    import paramiko

    check_cancelled(context, cancel)
    channel = context.transport.open_session(timeout=5)
    finished = Event()
    initialized = Event()
    client = None
    try:
        channel.settimeout(15)
        Thread(
            target=_watch_channel, args=(context, cancel, finished, initialized, channel),
            name="sftp-cancel-watch", daemon=True,
        ).start()
        check_cancelled(context, cancel)
        channel.invoke_subsystem("sftp")
        client = paramiko.SFTPClient(channel)
        initialized.set()
        check_cancelled(context, cancel)
        yield client
    finally:
        finished.set()
        try:
            if client is not None:
                client.close()
        finally:
            channel.close()


def remote_directory(sftp, directory: str) -> str:
    directory = directory.strip() or "."
    if any(ord(char) < 32 or ord(char) == 127 for char in directory):
        raise ValueError(tr("服务器目录无效"))
    if directory == "~" or directory.startswith("~/"):
        directory = posixpath.join(sftp.normalize("."), directory[2:] if directory != "~" else "")
    directory = sftp.normalize(directory)
    if not stat.S_ISDIR(sftp.stat(directory).st_mode or 0):
        raise ValueError(tr("目标不是目录：{0}", directory))
    return directory


def list_directory(context, cancel: Event, directory: str, *, listing_policy=None):
    with open_sftp(context, cancel) as sftp:
        if listing_policy is not None:
            message = listing_policy(directory)
            if message:
                raise ValueError(message)
            directory = remote_directory(sftp, directory)
            message = listing_policy(directory)
            if message:
                raise ValueError(message)
        return read_directory(sftp, context, cancel, directory)


def read_directory(sftp, context, cancel: Event, directory: str):
    directory = remote_directory(sftp, directory)
    entries = []
    for attributes in sftp.listdir_iter(directory, read_aheads=4):
        check_cancelled(context, cancel)
        name = attributes.filename
        _remote_name(name)
        mode = attributes.st_mode or 0
        entries.append(RemoteEntry(
            name, posixpath.join(directory, name), stat.S_ISDIR(mode),
            stat.S_ISLNK(mode), int(attributes.st_size or 0), int(attributes.st_mtime or 0), mode,
        ))
    return directory, sorted(entries, key=lambda entry: (not entry.directory, entry.name.casefold()))


def _remote_name(name: str) -> None:
    if not name or name in {".", ".."} or "/" in name or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise ValueError(tr("文件名无效：{0}", name))


def _local_name(name: str) -> None:
    _remote_name(name)
    if "\\" in name or (sys.platform == "win32" and (
        any(char in '<>:"|?*' for char in name) or name.endswith((".", " "))
        or PureWindowsPath(name).is_reserved()
    )):
        raise ValueError(tr("文件名无效：{0}", name))


def _is_local_link(path: Path) -> bool:
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def _local_target(root: Path, target: Path) -> Path:
    if _is_local_link(target) or not target.resolve().is_relative_to(root):
        raise ValueError(tr("目标路径超出下载目录：{0}", str(target)))
    return target


def _upload_plan(sftp, task) -> list[PlannedEntry]:
    destination = remote_directory(sftp, task.destination)
    task.remote_directory = destination
    task.remote_targets = tuple(posixpath.join(destination, Path(source).name) for source in task.sources)
    pending = []
    for source in reversed(task.sources):
        local = Path(source)
        _remote_name(local.name)
        pending.append((local, posixpath.join(destination, local.name)))
    plan = []
    while pending:
        check_cancelled(task.context, task.cancel)
        source, target = pending.pop()
        mode = source.lstat().st_mode
        if _is_local_link(source) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise ValueError(tr("不支持传输链接或特殊文件：{0}", str(source)))
        directory = stat.S_ISDIR(mode)
        plan.append(PlannedEntry(str(source), target, source.stat().st_size if not directory else 0, directory))
        if directory:
            for child in sorted(source.iterdir(), key=lambda item: item.name.casefold(), reverse=True):
                _remote_name(child.name)
                pending.append((child, posixpath.join(target, child.name)))
    return plan


def _download_plan(sftp, task, root: Path) -> list[PlannedEntry]:
    pending = []
    for source in reversed(task.sources):
        name = posixpath.basename(source.rstrip("/"))
        _local_name(name)
        pending.append((source, root / name))
    plan = []
    while pending:
        check_cancelled(task.context, task.cancel)
        source, target = pending.pop()
        _local_target(root, target)
        attributes = sftp.lstat(source)
        mode = attributes.st_mode or 0
        if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise ValueError(tr("不支持传输链接或特殊文件：{0}", source))
        directory = stat.S_ISDIR(mode)
        plan.append(PlannedEntry(source, str(target), int(attributes.st_size or 0) if not directory else 0, directory))
        if directory:
            children = list(sftp.listdir_iter(source, read_aheads=4))
            for child in sorted(children, key=lambda item: item.filename.casefold(), reverse=True):
                _local_name(child.filename)
                pending.append((posixpath.join(source, child.filename), target / child.filename))
    return plan


def _remote_stat(sftp, path: str):
    try:
        return sftp.lstat(path)
    except OSError as error:
        if error.errno != errno.ENOENT:
            raise
        return None


def _make_remote_directory(sftp, path: str) -> None:
    attributes = _remote_stat(sftp, path)
    if attributes is None:
        sftp.mkdir(path)
    elif not stat.S_ISDIR(attributes.st_mode or 0):
        raise ValueError(tr("目标不是目录：{0}", path))


def _upload_file(sftp, task, entry, progress, confirm, *, open_source=None) -> bool:
    if task.file_handler is not None and open_source is None:
        return task.file_handler.upload_file(sftp, task, entry, progress, confirm)
    existing = _remote_stat(sftp, entry.target)
    if existing is not None:
        if not stat.S_ISREG(existing.st_mode or 0):
            raise ValueError(tr("目标不是普通文件：{0}", entry.target))
        if not confirm(entry.target):
            return False
    temporary = posixpath.join(
        posixpath.dirname(entry.target), f".pipeterminal-upload-{uuid4().hex}.part",
    )
    try:
        current = 0
        source_file = open_source(entry.source) if open_source is not None else Path(entry.source).open("rb")
        with source_file as source, sftp.open(temporary, "wx") as target:
            target.set_pipelined(True)
            while True:
                check_cancelled(task.context, task.cancel)
                chunk = source.read(65536)
                if not chunk:
                    break
                target.write(chunk)
                current += len(chunk)
                progress(current)
        if current != entry.size or sftp.stat(temporary).st_size != entry.size:
            raise ValueError(tr("文件大小发生变化，请重试：{0}", entry.source))
        check_cancelled(task.context, task.cancel)
        if task.source_context is not None:
            check_cancelled(task.source_context, task.cancel)
        if existing is not None:
            sftp.chmod(temporary, stat.S_IMODE(existing.st_mode))
            try:
                sftp.posix_rename(temporary, entry.target)
            except OSError as error:
                if error.errno in {errno.ENOSYS, errno.EOPNOTSUPP} or str(error).lower() == "operation unsupported":
                    raise ValueError(tr("服务器不支持安全覆盖，请更换文件名后重试")) from error
                raise
        else:
            sftp.rename(temporary, entry.target)
        temporary = ""
        return True
    finally:
        if temporary:
            try:
                sftp.remove(temporary)
            except Exception:
                pass


def _download_file(sftp, task, entry, root, progress, confirm) -> bool:
    if task.file_handler is not None:
        return task.file_handler.download_file(sftp, task, entry, root, progress, confirm)
    target = _local_target(root, Path(entry.target))
    if target.exists() and not target.is_file():
        raise ValueError(tr("目标不是普通文件：{0}", str(target)))
    overwrite = target.exists()
    if overwrite and not confirm(str(target)):
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    _local_target(root, target)
    temporary = target.with_name(f".pipeterminal-download-{uuid4().hex}.part")
    try:
        with temporary.open("xb") as output:
            sftp.getfo(
                entry.source, output, callback=lambda current, _total: progress(current),
                max_concurrent_prefetch_requests=16,
            )
        if temporary.stat().st_size != entry.size:
            raise ValueError(tr("文件大小发生变化，请重试：{0}", entry.source))
        check_cancelled(task.context, task.cancel)
        _local_target(root, target)
        if not overwrite and target.exists() and not confirm(str(target)):
            return False
        os.replace(temporary, target)
        return True
    finally:
        temporary.unlink(missing_ok=True)


def transfer(task, progress, confirm) -> int:
    if task.source_context is not None and task.direction == "upload":
        if task.transfer_handler is None:
            raise PermissionError(tr("此功能需要付费授权"))
        return task.transfer_handler(task, progress, confirm)
    with open_sftp(task.source_context or task.context, task.cancel) as sftp:
        root = Path(task.destination).resolve() if task.direction == "download" else None
        if root is not None and not root.is_dir():
            raise ValueError(tr("目标不是目录：{0}", str(root)))
        plan = _upload_plan(sftp, task) if root is None else _download_plan(sftp, task, root)
        total = sum(entry.size for entry in plan)
        completed, skipped = 0, 0
        uploaded = set()
        root_targets = set(task.remote_targets) if root is None else set()
        progress(0, total, "")
        for entry in plan:
            check_cancelled(task.context, task.cancel)
            if entry.directory:
                if root is None:
                    _make_remote_directory(sftp, entry.target)
                    if entry.target in root_targets:
                        uploaded.add(entry.target)
                else:
                    _local_target(root, Path(entry.target)).mkdir(parents=True, exist_ok=True)
                continue
            name = posixpath.basename(entry.target) if root is None else Path(entry.target).name

            def file_progress(current: int) -> None:
                check_cancelled(task.context, task.cancel)
                progress(completed + current, total, name)

            copied = (
                _upload_file(sftp, task, entry, file_progress, confirm) if root is None
                else _download_file(sftp, task, entry, root, file_progress, confirm)
            )
            skipped += not copied
            if root is None and copied and entry.target in root_targets:
                uploaded.add(entry.target)
            completed += entry.size
            progress(completed, total, name)
        if root is None:
            task.uploaded_paths = tuple(path for path in task.remote_targets if path in uploaded)
        return skipped
