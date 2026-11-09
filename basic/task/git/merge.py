"""Merge in an isolated repository so failures never reset user worktrees."""

import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

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
        for directory in (target, source):
            if self._run(directory, "rev-parse", "--is-inside-work-tree").stdout.strip() != "true":
                raise GitMergeError(tr("不是有效的 Git 工作目录：{0}", directory))
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
        fetch_remote = self._run(target, "remote", "get-url", "origin").stdout.strip()
        if not fetch_remote or fetch_remote.startswith("-"):
            raise GitMergeError(tr("请配置唯一的远程仓库地址"))
        if ":" not in fetch_remote and not fetch_remote.startswith("/"):
            fetch_remote = str((target / fetch_remote).resolve())
        reference = "refs/heads/" + branch
        self.log(tr("准备合并：{0} → {1}", source_branch, branch))
        self.log(tr("仅合并源项目已提交的代码，原项目工作区保持不变"))
        with TemporaryDirectory(prefix="pipeterminal-git-", ignore_cleanup_errors=True) as temporary:
            workspace = Path(temporary) / "repository"
            workspace.mkdir()
            hooks = Path(temporary) / "hooks"
            hooks.mkdir()
            object_format = self._run(target, "rev-parse", "--show-object-format").stdout.strip()
            self._run(workspace, "init", "--quiet", f"--object-format={object_format}")
            self._run(workspace, "config", "core.hooksPath", str(hooks))
            self._copy_conversion_config(target, workspace)
            for key in ("user.name", "user.email"):
                identity = self._run(target, "config", "--get", key, check=False)
                if identity.returncode == 0:
                    self._run(workspace, "config", key, identity.stdout.strip())
            self.log(tr("读取远程目标分支"))
            self._run(workspace, "fetch", "--no-tags", "--no-recurse-submodules", fetch_remote, reference)
            before = self._run(workspace, "rev-parse", "FETCH_HEAD^{commit}").stdout.strip()
            local = self._run(target, "show-ref", "--hash", "--verify", reference, check=False)
            if local.returncode == 0:
                ancestor = self._run(workspace, "merge-base", "--is-ancestor", local.stdout.strip(), before, check=False)
                if ancestor.returncode != 0:
                    raise GitMergeError(tr("本地目标分支存在未推送或分叉提交，请先同步后再执行"))
            self._run(workspace, "checkout", "--quiet", "--detach", before)
            self._run(workspace, "fetch", "--no-tags", "--no-recurse-submodules", str(source), source_commit)
            self.log(tr("合并分支，不自动解决冲突"))
            self._merge(workspace, source_commit, properties, branch, source_branch, no_ff=True)
            merged = self._run(workspace, "rev-parse", "HEAD^{commit}").stdout.strip()
            if merged == before:
                self.log(tr("目标分支已包含源提交，无需推送"))
                return
            self.log(tr("推送目标分支"))
            self.log(tr("待推送提交：{0}", merged))
            uncertain = False
            try:
                result = self._run(workspace, "push", "--porcelain", remote, f"HEAD:{reference}", check=False, timeout=300)
                if result.returncode == 0:
                    self.log(tr("合并并推送成功，原项目工作区保持不变"))
                    return
                detail = result.stderr.strip() or result.stdout.strip()
            except (GitMergeError, OSError) as exc:
                detail = str(exc)
                uncertain = True
            self.log(tr("推送未正常结束，正在核实远程状态"))
            try:
                actual = self._remote_commit(workspace, remote, reference)
            except (GitMergeError, OSError) as exc:
                raise GitMergeError(tr("无法确认远程推送结果；本地未修改，请人工核实远程分支。{0}", detail)) from exc
            if actual == merged:
                self.log(tr("已确认远程收到本次提交，推送成功"))
                return
            if actual != before and actual and not uncertain:
                self.log(tr("远程已有更新，重新同步后重试推送"))
                self._run(workspace, "fetch", "--no-tags", "--no-recurse-submodules", remote, reference)
                self._merge(workspace, "FETCH_HEAD", properties, branch, tr("远程分支"))
                self._push_once(workspace, remote, reference)
                return
            if actual != before:
                raise GitMergeError(tr("远程分支已变化，未强制回退；本地未修改，请人工核实。{0}", detail))
            if uncertain:
                raise GitMergeError(tr("无法确认远程推送结果；本地未修改，请人工核实远程分支。{0}", detail))
            raise GitMergeError(tr("推送失败，远程未变化，原项目保持执行前状态。{0}", detail))

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

    def _merge(self, directory, commit, properties, left_label, right_label, no_ff=False):
        from .conflicts import resolve_conflicts
        args = ["-c", "commit.gpgsign=false", "-c", "merge.conflictStyle=diff3", "merge", "--no-edit", "--no-ff" if no_ff else "--ff", commit]
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
