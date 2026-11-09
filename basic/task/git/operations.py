"""Prepare updates in isolation, then publish with checked branch/index changes."""

from pathlib import Path
from tempfile import TemporaryDirectory
from common.i18n import tr
from .conflicts import resolve_conflicts
from .merge import GitMergeError, GitMergePush


class GitWorkflow(GitMergePush):
    def execute_action(self, action, properties):
        project = Path(properties["PROJECT_PATH"]).expanduser().resolve()
        project = Path(self._run(project, "rev-parse", "--show-toplevel").stdout.strip())
        branch = self._branch(project, "")
        reference = "refs/heads/" + branch
        for state in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer"):
            path = self._run(project, "rev-parse", "--git-path", state).stdout.strip()
            if (project / path).exists():
                raise GitMergeError(tr("仓库有未完成的 Git 操作，请先处理"))
        if self._run(project, "ls-files", "--unmerged", "-z", binary=True).stdout:
            raise GitMergeError(tr("仓库有未完成的 Git 操作，请先处理"))
        head = self._run(project, "rev-parse", "HEAD^{commit}").stdout.strip()
        index_tree = self._run(project, "write-tree").stdout.strip()
        head_tree = self._run(project, "rev-parse", "HEAD^{tree}").stdout.strip()
        staged = index_tree != head_tree
        message = properties.get("COMMIT_MESSAGE", "").strip()
        if action == "COMMIT_PUSH" and staged and not message:
            raise GitMergeError(tr("存在暂存改动，请填写提交说明"))
        if action == "PULL" and staged:
            raise GitMergeError(tr("请先处理暂存改动，再单独拉取代码"))
        remote_result = self._run(project, "config", "--get", f"branch.{branch}.remote", check=False)
        remote_name = remote_result.stdout.strip() or "origin"
        tracking = self._run(project, "config", "--get", f"branch.{branch}.merge", check=False).stdout.strip() or reference
        if not tracking.startswith("refs/heads/"):
            raise GitMergeError(tr("远程分支配置无效"))
        fetch_remote = self._remote_url(project, remote_name)
        push_name = (self._run(project, "config", "--get", f"branch.{branch}.pushRemote", check=False).stdout.strip()
                     or self._run(project, "config", "--get", "remote.pushDefault", check=False).stdout.strip()
                     or remote_name)
        push_remote = self._remote_url(project, push_name, push=True) if action == "COMMIT_PUSH" else None
        push_reference = self._push_reference(project, branch, remote_name, push_name, tracking) if action == "COMMIT_PUSH" else None
        with TemporaryDirectory(prefix="pipeterminal-git-", ignore_cleanup_errors=True) as temporary:
            workspace = Path(temporary) / "repository"
            workspace.mkdir()
            hooks = Path(temporary) / "hooks"
            hooks.mkdir()
            object_format = self._run(project, "rev-parse", "--show-object-format").stdout.strip()
            self._run(workspace, "init", "--quiet", f"--object-format={object_format}")
            self._run(workspace, "config", "core.hooksPath", str(hooks))
            self._copy_conversion_config(project, workspace)
            for key in ("user.name", "user.email"):
                value = self._run(project, "config", "--get", key, check=False)
                if value.returncode == 0:
                    self._run(workspace, "config", key, value.stdout.strip())
            self._run(workspace, "fetch", "--no-tags", "--no-recurse-submodules", str(project), head)
            self._run(workspace, "checkout", "--quiet", "--detach", head)
            self.log(tr("读取远程目标分支"))
            self._run(workspace, "fetch", "--no-tags", "--no-recurse-submodules", fetch_remote, tracking)
            remote_head = self._run(workspace, "rev-parse", "FETCH_HEAD").stdout.strip()
            ahead = self._run(workspace, "merge-base", "--is-ancestor", remote_head, head, check=False).returncode == 0
            fast_forward = self._run(workspace, "merge-base", "--is-ancestor", head, remote_head, check=False).returncode == 0
            if not ahead:
                if not fast_forward and properties.get("CONFLICT_POLICY", "rollback") != "merge":
                    raise GitMergeError(tr("分支已分叉，已停止并回退当前操作"))
                self._merge(workspace, remote_head, properties, branch, tr("远程分支"))
            if action == "COMMIT_PUSH" and staged:
                # Store a snapshot object without changing the user's branch or index.
                snapshot = self._run(project, "-c", "commit.gpgsign=false", "commit-tree", index_tree, "-p", head, "-m", message).stdout.strip()
                self._run(workspace, "fetch", "--no-tags", "--no-recurse-submodules", str(project), snapshot)
                result = self._run(workspace, "-c", "merge.conflictStyle=diff3", "merge", "--squash", "--no-commit", snapshot, check=False, timeout=300)
                if result.returncode:
                    unmerged = self._run(workspace, "ls-files", "--unmerged", "-z", binary=True).stdout
                    if not unmerged:
                        raise GitMergeError(result.stderr.strip() or result.stdout.strip())
                    if properties.get("CONFLICT_POLICY", "rollback") != "merge" or self.resolve is None:
                        raise GitMergeError(tr("存在冲突，已停止并回退当前操作"))
                    resolve_conflicts(self, workspace, tr("更新后的代码"), tr("已暂存改动"))
                if self._run(workspace, "diff", "--cached", "--quiet", check=False).returncode:
                    self._run(workspace, "-c", "commit.gpgsign=false", "commit", "-m", message, timeout=300)
            final = self._run(workspace, "rev-parse", "HEAD").stdout.strip()
            self._publish_local(project, workspace, branch, head, index_tree, final)
            if action == "PULL":
                self.log(tr("拉取完成"))
                return
            self.log(tr("本地更新已保存，开始推送"))
            try:
                # Retry once if the remote advanced while preparing the result.
                actual = self._remote_commit(workspace, push_remote, push_reference, allow_missing=True)
                if actual is not None and actual != remote_head:
                    self.log(tr("远程已有更新，重新同步后重试推送"))
                    self._run(workspace, "fetch", "--no-tags", "--no-recurse-submodules", push_remote, push_reference)
                    self._merge(workspace, "FETCH_HEAD", properties, branch, tr("远程分支"))
                    updated = self._run(workspace, "rev-parse", "HEAD").stdout.strip()
                    self._publish_local(project, workspace, branch, final, self._run(project, "rev-parse", f"{final}^{{tree}}").stdout.strip(), updated)
                self._push_once(workspace, push_remote, push_reference)
            except (GitMergeError, OSError) as exc:
                raise GitMergeError(tr("本地提交已保留，推送未完成：{0}", exc)) from exc
            self.log(tr("提交并推送完成"))

    def _push_reference(self, project, branch, fetch_name, push_name, tracking):
        source_ref = "refs/heads/" + branch
        specs = self._run(project, "config", "--get-all", f"remote.{push_name}.push", check=False).stdout.splitlines()
        destinations = []
        for spec in specs:
            if spec.startswith("+") or spec in {":", "+:"}:
                raise GitMergeError(tr("推送配置不适用于单分支流程，请明确设置目标分支"))
            source, separator, target = spec.partition(":")
            if not separator:
                target = source_ref if source == "HEAD" else source
            elif target == "HEAD":
                raise GitMergeError(tr("推送配置不适用于单分支流程，请明确设置目标分支"))
            if not source or not target:
                raise GitMergeError(tr("推送配置不适用于单分支流程，请明确设置目标分支"))
            source = source if source.startswith("refs/") or source == "HEAD" else "refs/heads/" + source
            target = target if target.startswith("refs/") else "refs/heads/" + target
            if "*" in source:
                if source.count("*") != 1 or target.count("*") != 1:
                    raise GitMergeError(tr("推送配置不适用于单分支流程，请明确设置目标分支"))
                prefix, suffix = source.split("*")
                if source_ref.startswith(prefix) and source_ref.endswith(suffix):
                    middle = source_ref[len(prefix):len(source_ref) - len(suffix) if suffix else None]
                    destinations.append(target.replace("*", middle))
            elif source in {source_ref, "HEAD"}:
                destinations.append(target)
        if specs:
            if len(destinations) != 1:
                raise GitMergeError(tr("推送配置不适用于单分支流程，请明确设置目标分支"))
            target = destinations[0]
        else:
            mode = self._run(project, "config", "--get", "push.default", check=False).stdout.strip() or "simple"
            if mode == "current" or (mode == "simple" and push_name != fetch_name):
                target = source_ref
            elif mode in {"upstream", "tracking", "simple"}:
                upstream = self._run(project, "config", "--get", f"branch.{branch}.merge", check=False).stdout.strip()
                if not upstream or push_name != fetch_name or (mode == "simple" and upstream != source_ref):
                    raise GitMergeError(tr("推送目标与当前分支不一致，请检查上游分支配置"))
                target = upstream
            else:
                raise GitMergeError(tr("推送配置不适用于单分支流程，请明确设置目标分支"))
        if not target.startswith("refs/heads/") or self._run(project, "check-ref-format", target, check=False).returncode:
            raise GitMergeError(tr("远程分支配置无效"))
        self.log(tr("推送目标：{0} / {1}", push_name, target[len("refs/heads/"):]))
        return target

    def _remote_url(self, project, name, push=False):
        if name == ".":
            return str(project)
        args = ["remote", "get-url"] + (["--push", "--all"] if push else [])
        remotes = self._run(project, *args, name).stdout.splitlines()
        if len(remotes) != 1 or not remotes[0] or remotes[0].startswith("-"):
            raise GitMergeError(tr("请配置唯一的远程仓库地址"))
        remote = remotes[0]
        if ":" not in remote and not remote.startswith("/"):
            remote = str((project / remote).resolve())
        return remote

    def _publish_local(self, project, workspace, branch, before, index_tree, after):
        from .publish import publish_local
        publish_local(self, project, workspace, branch, before, index_tree, after)
