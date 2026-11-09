"""Validated SFTP mutations and staged server-side copying; no Qt widgets."""

import errno
import posixpath
import shlex
import stat
from dataclasses import dataclass
from uuid import uuid4

from common.i18n import tr
from basic.shell.commands import AuxiliaryCommandRunner
from ..backend import check_cancelled, open_sftp, remote_directory, _remote_name, _remote_stat


@dataclass(frozen=True)
class PastePlan:
    source: str
    target: str
    conflict: bool


def concrete_path(sftp, path):
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError(tr("请选择明确的服务器路径"))
    path = posixpath.normpath(path)
    if not path.strip("/"):
        raise ValueError(tr("不能操作服务器根目录"))
    name = posixpath.basename(path)
    _remote_name(name)
    return posixpath.join(remote_directory(sftp, posixpath.dirname(path)), name)


def valid_name(name):
    _remote_name(name)
    if "\\" in name:
        raise ValueError(tr("文件名无效：{0}", name))
    return name


def has_selected_parent(path, selected):
    parent = posixpath.dirname(path)
    while parent and parent != "/":
        if parent in selected:
            return True
        parent = posixpath.dirname(parent)
    return False


def create(context, cancel, result, progress, directory, name, folder):
    name = valid_name(name)
    with open_sftp(context, cancel) as sftp:
        parent = remote_directory(sftp, directory)
        path = posixpath.join(parent, name)
        result["affected"] = (parent,)
        if _remote_stat(sftp, path) is not None:
            raise FileExistsError(tr("目标已存在：{0}", path))
        check_cancelled(context, cancel)
        if folder:
            sftp.mkdir(path)
        else:
            with sftp.open(path, "wx"):
                pass
        result["selected_paths"] = (path,)


def rename(context, cancel, result, progress, source, name):
    valid_name(name)
    with open_sftp(context, cancel) as sftp:
        source = concrete_path(sftp, source)
        target = posixpath.join(posixpath.dirname(source), name)
        result["affected"] = (posixpath.dirname(source),)
        if _remote_stat(sftp, target) is not None:
            raise FileExistsError(tr("目标已存在：{0}", target))
        check_cancelled(context, cancel)
        sftp.rename(source, target)
        result["selected_paths"] = (target,)


def remove_path(sftp, context, cancel, path):
    pending = [(path, False)]
    while pending:
        current, visited = pending.pop()
        check_cancelled(context, cancel)
        attributes = sftp.lstat(current)
        if stat.S_ISDIR(attributes.st_mode or 0):
            if visited:
                sftp.rmdir(current)
            else:
                pending.append((current, True))
                for entry in sftp.listdir_iter(current, read_aheads=4):
                    check_cancelled(context, cancel)
                    _remote_name(entry.filename)
                    pending.append((posixpath.join(current, entry.filename), False))
        else:
            sftp.remove(current)


def delete(context, cancel, result, progress, paths):
    with open_sftp(context, cancel) as sftp:
        paths = tuple(dict.fromkeys(concrete_path(sftp, path) for path in paths))
        result["affected"] = tuple(posixpath.dirname(path) for path in paths)
        # Deleting a selected parent already includes its selected descendants.
        selected = set(paths)
        roots = [path for path in paths if not has_selected_parent(path, selected)]
        for index, path in enumerate(roots):
            progress(index, len(roots), posixpath.basename(path))
            remove_path(sftp, context, cancel, path)
            progress(index + 1, len(roots), posixpath.basename(path))


def permission(context, cancel, result, progress, path, mode=None):
    with open_sftp(context, cancel) as sftp:
        path = concrete_path(sftp, path)
        attributes = sftp.lstat(path)
        if stat.S_ISLNK(attributes.st_mode or 0):
            raise ValueError(tr("不能修改链接的权限"))
        if mode is None:
            result["mode"] = stat.S_IMODE(attributes.st_mode or 0)
        else:
            if not 0 <= mode <= 0o7777:
                raise ValueError(tr("请输入 3 或 4 位八进制权限"))
            result["affected"] = (posixpath.dirname(path),)
            check_cancelled(context, cancel)
            sftp.chmod(path, mode)
            result["selected_paths"] = (path,)


def paste_preflight(context, cancel, result, progress, paths, directory):
    with open_sftp(context, cancel) as sftp:
        destination = remote_directory(sftp, directory)
        plans, names = [], set()
        sources = tuple(dict.fromkeys(concrete_path(sftp, path) for path in paths))
        selected = set(sources)
        for source in sources:
            check_cancelled(context, cancel)
            attributes = sftp.lstat(source)
            mode = attributes.st_mode or 0
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode) or stat.S_ISLNK(mode)):
                raise ValueError(tr("不支持传输链接或特殊文件：{0}", source))
            target = posixpath.join(destination, posixpath.basename(source))
            if target == source or (stat.S_ISDIR(mode) and (destination == source or destination.startswith(source + "/"))):
                raise ValueError(tr("不能粘贴到原位置或自身的子目录"))
            if has_selected_parent(source, selected):
                raise ValueError(tr("请不要同时选择目录及其内部项目"))
            if target in names:
                raise ValueError(tr("所选项目存在同名文件，请分开粘贴"))
            names.add(target)
            plans.append(PastePlan(source, target, _remote_stat(sftp, target) is not None))
        result["plans"] = tuple(plans)
        occupied = {posixpath.basename(plan.target) for plan in plans}
        for entry in sftp.listdir_iter(destination, read_aheads=4):
            check_cancelled(context, cancel)
            occupied.add(entry.filename)
        result["occupied"] = occupied


def next_copy_name(target, occupied):
    stem, extension = posixpath.splitext(posixpath.basename(target))
    number = 1
    while True:
        name = f"{stem} - copy{'' if number == 1 else f' ({number})'}{extension}"
        if name not in occupied:
            occupied.add(name)
            return posixpath.join(posixpath.dirname(target), name)
        number += 1


def paste(context, cancel, result, progress, plans, cut):
    result["completed_sources"] = []
    result["selected_paths"] = []
    with open_sftp(context, cancel) as sftp:
        result["affected"] = tuple(dict.fromkeys(posixpath.dirname(path) for plan, _replace in plans for path in (plan.source, plan.target)))
        for index, (plan, replace) in enumerate(plans):
            check_cancelled(context, cancel)
            source, target = concrete_path(sftp, plan.source), concrete_path(sftp, plan.target)
            attributes = sftp.lstat(source)
            destination = posixpath.dirname(target)
            if source == target or (stat.S_ISDIR(attributes.st_mode or 0) and (destination == source or destination.startswith(source + "/"))):
                raise ValueError(tr("不能粘贴到原位置或自身的子目录"))
            existing = _remote_stat(sftp, target)
            if existing is not None and not replace:
                raise FileExistsError(tr("目标已存在：{0}", target))
            staging = backup = ""
            try:
                if cut:
                    payload = source
                else:
                    staging = posixpath.join(posixpath.dirname(target), f".pipeterminal-copy-{uuid4().hex}")
                    sftp.mkdir(staging, 0o700)
                    payload = posixpath.join(staging, "content")
                    progress(index, len(plans), posixpath.basename(source))
                    AuxiliaryCommandRunner(context.transport, context.connection_stop).run(
                        f"exec cp -a -- {shlex.quote(source)} {shlex.quote(payload)}", cancel, timeout=300,
                    )
                check_cancelled(context, cancel)
                if _remote_stat(sftp, target) is not None:
                    if not replace:
                        raise FileExistsError(tr("目标已存在：{0}", target))
                    backup = posixpath.join(posixpath.dirname(target), f".pipeterminal-replace-{uuid4().hex}")
                    sftp.rename(target, backup)
                try:
                    sftp.rename(payload, target)
                except Exception:
                    if backup:
                        try:
                            sftp.rename(backup, target)
                            backup = ""
                        except Exception as restore_error:
                            raise RuntimeError(tr("替换失败，原内容保留在：{0}", backup)) from restore_error
                    raise
                result["completed_sources"].append(plan.source)
                result["selected_paths"].append(target)
                if backup:
                    remove_path(sftp, context, cancel, backup)
                    backup = ""
                progress(index + 1, len(plans), posixpath.basename(source))
            finally:
                if staging:
                    try:
                        remove_path(sftp, context, cancel, staging)
                    except Exception:
                        if not context.connection_stop.is_set() and context.transport.is_active():
                            from threading import Event
                            try:
                                with open_sftp(context, Event()) as cleanup:
                                    remove_path(cleanup, context, Event(), staging)
                            except Exception:
                                result.setdefault("leftovers", []).append(staging)
                        else:
                            result.setdefault("leftovers", []).append(staging)
                if backup:
                    result.setdefault("leftovers", []).append(backup)
