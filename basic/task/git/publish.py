"""Lock the branch and index while publishing a prepared local update."""

import os
import subprocess
from contextlib import ExitStack, contextmanager
from pathlib import Path
from queue import Empty, Queue
from tempfile import NamedTemporaryFile, TemporaryFile, mkdtemp
from threading import Thread
from common.i18n import tr
from .merge import GitMergeError
from .worktree_backup import WorktreeBackup


@contextmanager
def _lock(path):
    # Never remove another process's lock.
    handle = path.open("xb")
    try:
        yield
    finally:
        handle.close()
        path.unlink()


def _replace(path, content):
    temporary = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix="pipeterminal-index-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class _RefTransaction:
    def __init__(self, git, project, reference, before, after):
        self.errors = TemporaryFile()
        self.queue = Queue()
        self.process = subprocess.Popen(
            ["git", "-C", str(project), "update-ref", "--stdin", "-m", "PipeTerminal workflow"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.errors,
            text=True, encoding="utf-8", env=git._environment(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.reader = Thread(target=self._read, daemon=True)
        self.reader.start()
        try:
            self.command("start")
            self.process.stdin.write(f"update HEAD {after} {before}\n")
            self.command("prepare")
            # Updating HEAD locks both the symbolic ref and its current branch.
            if git._run(project, "symbolic-ref", "HEAD").stdout.strip() != reference:
                raise GitMergeError(tr("操作期间本地仓库发生变化，已停止更新"))
        except Exception:
            self.close()
            raise

    def _read(self):
        for line in self.process.stdout:
            self.queue.put(line.strip())
        self.queue.put(None)

    def command(self, command):
        try:
            self.process.stdin.write(command + "\n")
            self.process.stdin.flush()
            response = self.queue.get(timeout=30)
        except (Empty, OSError) as exc:
            raise GitMergeError(tr("Git 操作超时")) from exc
        if response != command + ": ok":
            self.errors.seek(0)
            detail = self.errors.read().decode("utf-8", "replace").strip()
            raise GitMergeError(detail or tr("Git 操作失败"))

    def close(self):
        if self.process.stdin and not self.process.stdin.closed:
            try:
                self.process.stdin.close()
            except OSError:
                pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.reader.join(timeout=2)
        self.process.stdout.close()
        self.errors.close()


def publish_local(git, project, workspace, branch, before, index_tree, after):
    # Fetch before the final validation: network/disk delays must not widen the write window.
    git._run(project, "fetch", "--no-tags", "--no-write-fetch-head", "--no-recurse-submodules", str(workspace), after)
    index_path = (project / git._run(project, "rev-parse", "--git-path", "index").stdout.strip()).resolve()
    reference = "refs/heads/" + branch
    for pending in index_path.parent.glob("pipeterminal-recovery-*"):
        if (pending / "state.txt").is_file() and not (pending / "complete").exists():
            raise GitMergeError(tr("存在未处理的恢复记录，请先检查：{0}", pending))
    recovery = None
    cleanup = False
    with ExitStack() as stack:
        stack.enter_context(_lock(Path(str(index_path) + ".lock")))
        if git._branch(project, "") != branch or git._run(project, "rev-parse", reference).stdout.strip() != before:
            raise GitMergeError(tr("操作期间本地仓库发生变化，已停止更新"))
        original = index_path.read_bytes()
        recovery = Path(mkdtemp(prefix="pipeterminal-recovery-", dir=index_path.parent))
        alternate = recovery / "index"
        alternate.write_bytes(original)
        _replace(recovery / "original-index", original)
        (recovery / "state.txt").write_text(f"{reference}\n{before}\n{after}\n{index_tree}\n", encoding="utf-8")
        backup = WorktreeBackup(project, recovery)
        transaction = None
        checked_out = False
        checkout_started = False
        committed = False
        try:
            # Expand split-index metadata before using an index outside its original directory.
            git._run(project, "update-index", "--no-split-index", index_file=alternate)
            if git._run(project, "write-tree", index_file=alternate).stdout.strip() != index_tree:
                raise GitMergeError(tr("操作期间本地仓库发生变化，已停止更新"))
            transaction = _RefTransaction(git, project, reference, before, after)
            backup.capture(git, workspace, index_tree, after)
            checkout_started = True
            git._run(project, "read-tree", "-m", "-u", index_tree, after, index_file=alternate)
            checked_out = True
            _replace(index_path, alternate.read_bytes())
            try:
                transaction.command("commit")
                committed = True
            except Exception:
                # A lost acknowledgement must not undo an already committed reference.
                transaction.close()
                transaction = None
                committed = git._run(project, "rev-parse", reference).stdout.strip() == after
                if not committed:
                    raise
            cleanup = True
        except Exception as exc:
            try:
                if not committed and git._run(project, "rev-parse", reference).stdout.strip() == before:
                    if checkout_started:
                        if transaction is None:
                            transaction = _RefTransaction(git, project, reference, before, before)
                        backup.restore()
                    _replace(index_path, original)
                    cleanup = True
            except Exception as restore_error:
                raise GitMergeError(tr("自动恢复未完成，恢复记录保存在：{0}", recovery)) from restore_error
            if not cleanup:
                git.log(tr("恢复记录保存在：{0}", recovery))
            raise
        finally:
            if transaction is not None:
                transaction.close()
            if cleanup:
                try:
                    _replace(recovery / "complete", b"complete")
                    backup.cleanup()
                    for name in ("index", "original-index", "state.txt", "complete"):
                        (recovery / name).unlink(missing_ok=True)
                    recovery.rmdir()
                except OSError:
                    git.log(tr("恢复记录保存在：{0}", recovery))
