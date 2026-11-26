"""Merge committed changes directly in the configured target repository."""

import os
import subprocess
from pathlib import Path

from common.i18n import tr


class GitMergeError(RuntimeError):
    pass


class GitMergePush:
    def __init__(self, log, resolve=None):
        self.log = log
        self.resolve = resolve

    def _environment(self, index_file=None):
        environment = os.environ.copy()
        for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE"):
            environment.pop(key, None)
        environment.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never", LC_ALL="C.UTF-8")
        if index_file is not None:
            environment["GIT_INDEX_FILE"] = str(index_file)
        return environment

    def _run(self, directory, *arguments, check=True, timeout=120, binary=False, input_data=None, index_file=None):
        environment = self._environment(index_file)
        try:
            result = subprocess.run(
                ["git", "-C", str(directory), *arguments], capture_output=True,
                text=not binary, encoding=None if binary else "utf-8", errors=None if binary else "replace", env=environment, input=input_data,
                timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except FileNotFoundError as exc:
            raise GitMergeError(tr("未找到 Git，请先安装并配置 PATH")) from exc
        except subprocess.TimeoutExpired as exc:
            raise GitMergeError(tr("Git 操作超时")) from exc
        if check and result.returncode:
            detail = result.stderr.strip() or result.stdout.strip()
            raise GitMergeError(detail.decode("utf-8", "replace") if isinstance(detail, bytes) else detail or tr("Git 操作失败"))
        return result

    def _remote_commit(self, directory, remote, reference, allow_missing=False):
        result = self._run(directory, "ls-remote", "--exit-code", remote, reference, check=False)
        if allow_missing and result.returncode == 2:
            return None
        if result.returncode:
            raise GitMergeError(result.stderr.strip() or tr("Git 操作失败"))
        records = [line.split() for line in result.stdout.splitlines()]
        return next((parts[0] for parts in records if len(parts) == 2 and parts[1] == reference), None)

    def _branch(self, directory, name):
        branch = name.strip()
        if not branch:
            result = self._run(directory, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
            branch = result.stdout.strip()
            if result.returncode or not branch:
                raise GitMergeError(tr("无法读取当前分支，请填写分支名称：{0}", directory))
        if branch.startswith("-") or self._run(directory, "check-ref-format", "refs/heads/" + branch, check=False).returncode:
            raise GitMergeError(tr("分支名称无效：{0}", branch))
        return branch

    def execute(self, properties):
        target = Path(properties["TARGET_PROJECT_PATH"]).expanduser().resolve()
        source = Path(properties["SOURCE_PROJECT_PATH"]).expanduser().resolve()
        self.log(tr("检查 Git 工作区"))
        roots = []
        for directory in (target, source):
            top = self._run(directory, "rev-parse", "--show-toplevel", check=False)
            if top.returncode or not top.stdout.strip():
                raise GitMergeError(tr("不是有效的 Git 工作目录：{0}", directory))
            roots.append(Path(top.stdout.strip()).resolve())
        target, source = roots
        source_branch = self._branch(source, properties.get("SOURCE_BRANCH", ""))
        branch = self._branch(target, properties.get("TARGET_BRANCH", ""))
        repositories = []
        for directory in (source, target):
            common = self._run(directory, "rev-parse", "--git-common-dir").stdout.strip()
            repositories.append((directory / common).resolve())
        if repositories[0] == repositories[1] and source_branch == branch:
            raise GitMergeError(tr("源分支与目标分支相同"))
        source_commit = self._run(source, "rev-parse", "--verify", f"refs/heads/{source_branch}^{{commit}}").stdout.strip()
        remote = self._run(target, "remote", "get-url", "--push", "--all", "origin").stdout.splitlines()
        if len(remote) != 1:
            raise GitMergeError(tr("origin 必须配置唯一的推送地址"))
        remote = remote[0]
        if not remote or remote.startswith("-"):
            raise GitMergeError(tr("origin 推送地址无效"))
        # Resolve local remotes relative to the configured project, not the temporary repo.
        if ":" not in remote and not remote.startswith("/"):
            remote = str((target / remote).resolve())
        self.log(tr("准备合并：{0} → {1}", source_branch, branch))
        self.log(tr("源分支本地提交：{0}", source_commit))
        self._ensure_no_operation(target)
        if self._run(target, "status", "--porcelain", "--ignore-submodules=none").stdout:
            raise GitMergeError(tr("目标 Git 工作区有本地改动，请处理后再合并：{0}", target))

        reference = "refs/heads/" + branch
        if self._run(target, "show-ref", "--verify", "--quiet", reference, check=False).returncode:
            raise GitMergeError(tr("目标本地分支不存在：{0}", branch))
        current = self._run(target, "symbolic-ref", "--quiet", "HEAD", check=False)
        if current.stdout.strip() != reference:
            self._run(target, "switch", "--no-guess", "--no-overwrite-ignore", branch)

        if self._run(target, "cat-file", "-e", f"{source_commit}^{{commit}}", check=False).returncode:
            self.log(tr("从本地源目录导入提交"))
            self._run(target, "fetch", "--no-tags", "--no-write-fetch-head", "--no-recurse-submodules", str(source), source_commit)
        self.log(tr("合并分支，不自动解决冲突"))
        self._merge(target, source_commit, properties, branch, source_branch, no_ff=True, preserve_workspace=True)

        merged = self._run(target, "rev-parse", "HEAD^{commit}").stdout.strip()
        self.log(tr("目标工作区当前提交：{0}", merged))
        self.log(tr("推送目标分支"))
        self.log(tr("待推送提交：{0}", merged))
        try:
            self._push_once(target, remote, reference)
        except (GitMergeError, OSError) as error:
            raise GitMergeError(tr("本地提交已保留，推送未完成：{0}", error)) from error
        self.log(tr("合并并推送成功"))

    def _ensure_no_operation(self, directory):
        git_dir = Path(self._run(directory, "rev-parse", "--absolute-git-dir").stdout.strip())
        if any((git_dir / name).exists() for name in (
            "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer",
        )):
            raise GitMergeError(tr("仓库有未完成的 Git 操作，请先处理"))

    def _copy_conversion_config(self, project, workspace):
        for key in ("core.autocrlf", "core.eol", "core.safecrlf", "core.checkRoundtripEncoding", "core.attributesFile"):
            value = self._run(project, "config", "--get", key, check=False)
            if value.returncode == 0:
                setting = value.stdout.rstrip("\n")
                if key == "core.attributesFile":
                    setting = str((Path(project) / Path(setting).expanduser()).resolve())
                self._run(workspace, "config", key, setting)
        filters = self._run(project, "config", "--null", "--get-regexp", r"^filter\.", check=False).stdout
        for record in filters.split("\0"):
            if "\n" in record:
                key, value = record.split("\n", 1)
                self._run(workspace, "config", key, value)
        info = self._run(project, "rev-parse", "--git-path", "info/attributes").stdout.strip()
        source = Path(project) / info
        if source.is_file():
            target = Path(workspace) / ".git" / "info" / "attributes"
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(source.read_bytes())

    def _merge(self, directory, commit, properties, left_label, right_label, no_ff=False, *, preserve_workspace=False):
        args = ["-c", "commit.gpgsign=false", "-c", "merge.conflictStyle=diff3", "merge", "--no-edit", "--no-ff" if no_ff else "--ff"]
        if preserve_workspace:
            args.extend(("--no-overwrite-ignore", "--no-autostash"))
        self._run_merge_command(directory, (*args, commit), properties, left_label, right_label, in_place=preserve_workspace)

    def _run_merge_command(self, directory, args, properties, left_label, right_label, *, in_place=False):
        from .conflicts import resolve_conflicts

        try:
            result = self._run(directory, *args, check=False, timeout=300)
            if result.returncode == 0:
                return
            unmerged = self._run(directory, "ls-files", "--unmerged", "-z", binary=True).stdout
            if not unmerged:
                raise GitMergeError(result.stderr.strip() or result.stdout.strip() or tr("Git 操作失败"))
            if properties.get("CONFLICT_POLICY", "rollback") != "merge" or self.resolve is None:
                raise GitMergeError(tr("存在冲突，已停止并回退当前操作"))
            resolve_conflicts(self, directory, left_label, right_label)
            self._run(directory, "-c", "commit.gpgsign=false", "commit", "--no-edit", timeout=300)
        except Exception as error:
            if in_place and self._run(directory, "rev-parse", "--verify", "--quiet", "MERGE_HEAD", check=False).returncode == 0:
                try:
                    self._run(directory, "merge", "--abort")
                except GitMergeError as abort_error:
                    raise GitMergeError(tr("无法撤销本地合并：{0}；{1}", error, abort_error)) from abort_error
            raise

    def _push_once(self, directory, remote, reference):
        expected = self._run(directory, "rev-parse", "HEAD").stdout.strip()
        try:
            result = self._run(directory, "push", "--porcelain", remote, f"HEAD:{reference}", check=False, timeout=300)
            if result.returncode == 0:
                return
            detail = result.stderr.strip() or result.stdout.strip()
        except GitMergeError as exc:
            detail = str(exc)
        try:
            actual = self._remote_commit(directory, remote, reference)
        except GitMergeError as exc:
            raise GitMergeError(tr("无法确认推送结果，请核实远程分支：{0}", detail)) from exc
        if actual != expected:
            raise GitMergeError(tr("推送未完成，请检查日志后重试：{0}", detail))
