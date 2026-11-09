"""Durable snapshots of only the worktree paths touched by a prepared update."""

import hashlib
import json
import os
import shutil
import stat
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile
from common.i18n import tr
from .merge import GitMergeError


def _state(path):
    if path.is_symlink():
        return {"kind": "link", "target": os.readlink(path), "directory": path.is_dir()}
    if path.is_dir():
        return {"kind": "directory"}
    if path.is_file():
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return {"kind": "file", "digest": digest.hexdigest(), "mode": stat.S_IMODE(path.stat().st_mode)}
    if path.exists():
        raise GitMergeError(tr("无法安全处理冲突路径：{0}", path))
    return {"kind": "missing"}


def _state_at(root, relative):
    path = root / relative
    for parent in path.parents:
        if parent == root:
            break
        # Descendants of a symlink/file are absent from this worktree structure;
        # never follow them into another directory during backup or restore.
        if parent.is_symlink() or parent.is_file():
            return {"kind": "missing"}
    return _state(path)


class WorktreeBackup:
    def __init__(self, project, recovery):
        self.project = Path(project).resolve()
        self.recovery = recovery
        self.entries = []
        (recovery / "files").mkdir()

    def _path(self, relative):
        parts = PurePosixPath(relative)
        if parts.is_absolute() or ".." in parts.parts or "\\" in relative or ":" in relative:
            raise GitMergeError(tr("无法安全处理冲突路径：{0}", relative))
        return self.project / relative

    def capture(self, git, workspace, before_tree, after):
        raw = git._run(self.project, "diff-tree", "--no-commit-id", "--name-only", "--no-renames", "-r", "-z", before_tree, after, binary=True).stdout
        paths = set()
        for value in raw.split(b"\0"):
            if value:
                relative = PurePosixPath(value.decode("utf-8", "strict"))
                paths.add(relative.as_posix())
                paths.update(parent.as_posix() for parent in relative.parents if parent != PurePosixPath("."))
        for relative in sorted(paths, key=lambda name: (name.count("/"), name)):
            path = self._path(relative)
            before = _state_at(self.project, relative)
            entry = {"path": relative, "before": before, "after": _state_at(Path(workspace), relative)}
            if before["kind"] == "file":
                saved = str(len(self.entries))
                backup = self.recovery / "files" / saved
                shutil.copy2(path, backup)
                with backup.open("rb") as stream:
                    os.fsync(stream.fileno())
                if _state(backup) != before or _state(path) != before:
                    raise GitMergeError(tr("操作期间本地仓库发生变化，已停止更新"))
                entry["backup"] = saved
            self.entries.append(entry)
        with (self.recovery / "worktree.json").open("w", encoding="utf-8") as stream:
            json.dump({"project": str(self.project), "entries": self.entries}, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())

    def restore(self):
        # Preserve edits made by an external editor during this operation.
        for entry in self.entries:
            current = _state_at(self.project, entry["path"])
            if current not in (entry["before"], entry["after"]):
                raise GitMergeError(tr("工作文件发生额外变化，已保留备份：{0}", self.recovery))
        for entry in reversed(self.entries):
            path = self._path(entry["path"])
            current = _state_at(self.project, entry["path"])
            original = entry["before"]
            if current == original:
                continue
            if current["kind"] != original["kind"] or original["kind"] == "missing":
                if current["kind"] == "directory":
                    path.rmdir()  # Never recursively remove a directory.
                elif current["kind"] != "missing":
                    path.unlink()
        for entry in self.entries:
            path = self._path(entry["path"])
            original = entry["before"]
            if _state_at(self.project, entry["path"]) == original:
                continue
            if original["kind"] == "directory":
                path.mkdir(exist_ok=True)
            elif original["kind"] == "link":
                if path.is_symlink():
                    path.unlink()
                os.symlink(original["target"], path, target_is_directory=original["directory"])
            elif original["kind"] == "file":
                temporary = None
                try:
                    with NamedTemporaryFile(dir=path.parent, prefix=".pipeterminal-restore-", delete=False) as stream:
                        temporary = Path(stream.name)
                    shutil.copy2(self.recovery / "files" / entry["backup"], temporary)
                    os.replace(temporary, path)
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
        for entry in self.entries:
            if _state_at(self.project, entry["path"]) != entry["before"]:
                raise GitMergeError(tr("自动恢复未完成，恢复记录保存在：{0}", self.recovery))

    def cleanup(self):
        for path in (self.recovery / "files").iterdir():
            path.unlink()
        (self.recovery / "files").rmdir()
        (self.recovery / "worktree.json").unlink(missing_ok=True)
