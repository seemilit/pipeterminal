"""GUI-side file actions, captured menu targets and isolated editor windows."""

import posixpath
import re
import shlex
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMenu, QMessageBox

from common.i18n import tr
from common.licensing.prompt import prompt_activation
from common.i18n.widgets import QCheckBox, QProgressDialog
from ..clipboard import get_clipboard
from ..context_menu import FileMenuContext, build_remote_menu
from ..model import RemoteEntry
from . import backend

from common.i18n.errors import error_message


class RemoteFileActions(QObject):
    command_requested = Signal(str)

    def __init__(self, workspace, controller):
        super().__init__(workspace)
        self.workspace, self.controller = workspace, controller
        self.clipboard = get_clipboard()
        self._owner = uuid4().hex
        self._callbacks = {}
        self._editors = {}
        self._progress_dialogs = {}
        self._closed = False
        self._terminal_menu = None
        controller.completed.connect(self._completed)
        controller.progress_changed.connect(self._progress)
        self.clipboard.changed.connect(self._update_cut)
        self.clipboard.status.connect(self._clipboard_status)
        self.bind_clipboard_shortcuts(workspace.local.tree, local=True)

    def bind_clipboard_shortcuts(self, view, *, local=False):
        if getattr(view, "_clipboard_bound", False):
            return
        view._clipboard_bound = True
        for key, action in ((QKeySequence.StandardKey.Copy, "copy"), (QKeySequence.StandardKey.Paste, "paste")):
            shortcut = QShortcut(QKeySequence(key), view)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda value=action: self._clipboard_action(value, local))

    def _clipboard_action(self, action, local):
        if self._closed:
            return
        if local:
            if action == "copy":
                self.clipboard.set_local(self.workspace.local.selected_paths())
            else:
                self._paste_local(self.workspace.local.directory)
        elif self.workspace.remote.ready:
            entries = tuple(item.data(0, Qt.ItemDataRole.UserRole) for item in self.workspace.remote.tree.selectedItems())
            context = FileMenuContext(self._connection(), self.workspace.remote.directory, entries)
            if action != "copy" or entries:
                self.execute(action, context)

    def _clipboard_status(self, message):
        if not self._closed and self.clipboard.get(self._connection()) is not None:
            self.workspace.remote.status.setText(message)

    def _paste_local(self, directory):
        provider = self.clipboard.provider
        if provider is not None:
            provider.paste_local(self, directory)
        else:
            value = self.clipboard.get(self._connection(), allow_other=True)
            if value is not None and not value.cut:
                self._prompt_file_bridge()

    def _prompt_file_bridge(self):
        prompt_activation(self.workspace.transfer_controller.registry, self.workspace, tr("跨设备文件复制"))

    def _connection(self):
        session = self.workspace._session
        return session.connection_context() if session is not None else None

    def show_terminal_menu(self, terminal, reference, cwd, position, menu=None, allowed=None, *, metadata_cache=None):
        if self._closed:
            if menu is not None:
                menu.deleteLater()
            return
        if self._terminal_menu is None:
            from .terminal_menu import TerminalFileMenu
            self._terminal_menu = TerminalFileMenu(self, cache=metadata_cache)
        self._terminal_menu.show(terminal, reference, cwd, position, menu, allowed)

    def show_remote_menu(self, view, position, tree=False):
        if self._closed:
            return
        connection = self._connection()
        if tree:
            item = view.itemAt(position)
            if item is not None and item.data(0, Qt.ItemDataRole.UserRole) is not None:
                view.setCurrentItem(item)
                path = item.data(0, Qt.ItemDataRole.UserRole)
                entries = (RemoteEntry(posixpath.basename(path) or "/", path, True, False, 0, 0),)
                directory = path
            else:
                view.clearSelection()
                entries, directory = (), self.workspace.remote.directory
        else:
            if view is not self.workspace.remote.tree:
                return
            item = view.itemAt(position)
            if item is None:
                view.clearSelection()
            elif not item.isSelected():
                view.clearSelection()
                view.setCurrentItem(item)
                item.setSelected(True)
            entries = tuple(item.data(0, Qt.ItemDataRole.UserRole) for item in view.selectedItems() if item.data(0, Qt.ItemDataRole.UserRole) is not None)
            directory = self.workspace.remote.directory
        context = FileMenuContext(connection, directory, entries, tree)
        enabled = connection is not None and not self.controller.busy and (tree or self.workspace.remote.ready)
        menu = build_remote_menu(self.workspace, context, self.execute, enabled=enabled,
                                 can_paste=self.clipboard.can_paste(connection))
        try:
            menu.exec(view.viewport().mapToGlobal(position))
        finally:
            menu.deleteLater()

    def show_local_menu(self, view, position):
        local = self.workspace.local
        index = view.indexAt(position)
        if index.isValid() and not view.selectionModel().isSelected(index):
            view.setCurrentIndex(index)
        elif not index.isValid():
            view.clearSelection()
        paths = tuple(local.selected_paths())
        context = self._connection()
        destination = self.workspace.remote.directory
        menu = QMenu(self.workspace)
        copy_files = menu.addAction(tr("复制"))
        copy_files.setEnabled(bool(paths))
        copy_files.triggered.connect(lambda _checked=False: self.clipboard.set_local(paths))
        paste_files = menu.addAction(tr("粘贴到当前目录"))
        value = self.clipboard.get(context, allow_other=True)
        paste_files.setEnabled(value is not None and not value.cut)
        local_directory = local.directory
        paste_files.triggered.connect(lambda _checked=False: self._paste_local(local_directory))
        menu.addSeparator()
        upload = menu.addAction(tr("上传选中项到右侧目录"))
        upload.setEnabled(bool(paths) and self.workspace.remote.ready and context is not None and not self.controller.busy)
        upload.triggered.connect(lambda _checked=False: self._upload_local(paths, destination, context))
        folder = menu.addAction(tr("打开所在文件夹"))
        folder.setEnabled(bool(paths))
        folder.triggered.connect(lambda _checked=False: self._open_local(paths[0]) if paths else None)
        copy = menu.addAction(tr("复制路径"))
        copy.setEnabled(bool(paths))
        copy.triggered.connect(lambda _checked=False: QApplication.clipboard().setText("\n".join(paths)))
        refresh = menu.addAction(tr("刷新"))
        refresh.triggered.connect(lambda _checked=False: local.open_directory(local.directory))
        try:
            menu.exec(view.viewport().mapToGlobal(position))
        finally:
            menu.deleteLater()

    def _open_local(self, path):
        value = Path(path)
        directory = value if value.is_dir() else value.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory.resolve())))

    def _upload_local(self, paths, destination, context):
        self._queue_snapshot_transfer("upload", paths, destination, context)

    def _queue_snapshot_transfer(self, direction, paths, destination, context):
        if paths and context is not None and self.controller.current(context) and not self.controller.busy:
            self.workspace.transfer_controller.submit(direction, list(paths), destination)

    def execute(self, action, context, *, choose_download_directory=False):
        if self._closed or context.connection is None or not self.controller.current(context.connection) or self.controller.busy:
            return
        paths = tuple(entry.path for entry in context.entries)
        first = context.entries[0] if context.entries else None
        directory = context.directory
        if action == "open":
            self.workspace.browse_directory(first.path)
        elif action == "parent":
            self.workspace.browse_directory(posixpath.dirname(first.path))
        elif action == "up":
            self.workspace.browse_directory(posixpath.dirname(directory.rstrip("/")) or "/")
        elif action == "refresh":
            self.workspace.browse_directory(directory)
        elif action == "copy_path":
            QApplication.clipboard().setText("\n".join(paths))
        elif action == "copy_windows":
            if self.clipboard.provider is None:
                self._prompt_file_bridge()
            else:
                self.clipboard.set(context.connection, paths, False)
        elif action in {"copy", "cut"}:
            self.clipboard.set(context.connection, paths, action == "cut")
            self._update_cut()
        elif action in {"paste", "paste_into"}:
            self._paste(context, first.path if action == "paste_into" else directory)
        elif action in {"upload", "upload_folder"}:
            if action == "upload_folder":
                selected = QFileDialog.getExistingDirectory(self.workspace, tr("选择目录"), self.workspace.local.directory)
                sources = [selected] if selected else []
            else:
                sources, _filter = QFileDialog.getOpenFileNames(self.workspace, tr("上传"), self.workspace.local.directory)
            self._upload_local(sources, directory, context.connection)
        elif action == "download":
            target = self.workspace.local.directory
            if choose_download_directory or self.workspace._embedded:
                target = QFileDialog.getExistingDirectory(self.workspace, tr("选择目录"), target)
            if target and self.controller.current(context.connection):
                self._queue_snapshot_transfer("download", paths, target, context.connection)
        elif action in {"new_file", "new_directory", "rename"}:
            self._name_action(action, context)
        elif action == "delete":
            shown = "\n".join(paths[:8])
            if len(paths) > 8:
                shown += tr("\n……共 {0} 项", len(paths))
            box = QMessageBox(self.workspace)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle(tr("确认删除"))
            box.setTextFormat(Qt.TextFormat.PlainText)
            box.setText(tr("将永久删除以下项目，文件夹包括内部内容：\n{0}", shown))
            box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            box.setDefaultButton(QMessageBox.StandardButton.No)
            answer = box.exec()
            box.deleteLater()
            if answer == QMessageBox.StandardButton.Yes:
                self._run("删除", context, lambda ctx, cancel, result, progress: backend.delete(ctx, cancel, result, progress, paths),
                          affected=tuple(posixpath.dirname(path) for path in paths), paths=paths)
        elif action == "edit":
            self._edit(context, first.path)
        elif action == "chmod":
            self._run("读取权限", context, lambda ctx, cancel, result, progress: backend.permission(ctx, cancel, result, progress, first.path),
                      callback=lambda job, error: self._permission_prompt(context, first.path, job, error), paths=paths)
        elif action in {"script", "script_args", "tail_follow", "tail_lines", "search"}:
            self._command(action, context, first.path)

    def _name_action(self, action, context):
        first = context.entries[0] if context.entries else None
        title = "重命名" if action == "rename" else "新建文件夹" if action == "new_directory" else "新建文件"
        value, accepted = QInputDialog.getText(self.workspace, tr(title), tr("名称："), text=first.name if action == "rename" else "")
        if not accepted:
            return
        try:
            value = backend.valid_name(value.strip())
        except ValueError as exc:
            QMessageBox.warning(self.workspace, tr(title), error_message(exc))
            return
        if action == "rename":
            if value == first.name:
                return
            work = lambda ctx, cancel, result, progress: backend.rename(ctx, cancel, result, progress, first.path, value)
            affected = (posixpath.dirname(first.path),)
        else:
            work = lambda ctx, cancel, result, progress: backend.create(ctx, cancel, result, progress, context.directory, value, action == "new_directory")
            affected = (context.directory,)
        self._run(title, context, work, affected=affected, paths=(context.directory, value))

    def _run(self, title, context, work, *, affected=(), paths=(), callback=None):
        job = self.controller.start(tr(title), context.connection, work, owner=self._owner, affected=affected, paths=paths)
        if job is None:
            return None
        self._callbacks[job.id] = (context, callback)
        dialog = QProgressDialog(tr("正在处理文件操作…"), tr("取消"), 0, 0, self.workspace)
        dialog.setWindowTitle(tr(title))
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.setMinimumDuration(500)
        dialog.setValue(0)
        dialog.setAutoClose(False)
        dialog.canceled.connect(job.cancel.set)
        self._progress_dialogs[job.id] = dialog
        return job

    def _progress(self, identifier, current, total, name):
        dialog = self._progress_dialogs.get(identifier)
        if dialog is not None:
            dialog.setRange(0, total)
            dialog.setValue(current)
            dialog.setLabelText(tr("正在处理：{0}/{1} {2}", current, total, name))

    def _completed(self, job, error):
        if self._closed or job.owner != self._owner:
            return
        dialog = self._progress_dialogs.pop(job.id, None)
        if dialog is not None:
            dialog.close()
            dialog.deleteLater()
        context, callback = self._callbacks.pop(job.id, (None, None))
        if callback is not None:
            callback(job, error)
        else:
            self._report_result(job, error)

    def _report_result(self, job, error):
        if error:
            QMessageBox.warning(self.workspace, job.label, tr("操作失败：{0}", error))
        else:
            self.workspace.remote.status.setText(tr("操作完成"))
            selected = job.result.get("selected_paths", ())
            if selected:
                self.workspace.select_operation_results(selected)
        leftovers = job.result.get("leftovers", ())
        if leftovers:
            QMessageBox.warning(self.workspace, tr("文件操作"), tr("以下临时内容未清理：\n{0}", "\n".join(leftovers)))

    def _permission_prompt(self, context, path, job, error):
        if error:
            self._report_result(job, error)
            return
        value, accepted = QInputDialog.getText(self.workspace, tr("修改文件权限"), tr("八进制权限（如 644、755）："), text=f"{job.result['mode']:o}")
        if not accepted:
            return
        if re.fullmatch(r"[0-7]{3,4}", value.strip()) is None:
            QMessageBox.warning(self.workspace, tr("修改文件权限"), tr("请输入 3 或 4 位八进制权限"))
            return
        mode = int(value, 8)
        self._run("修改文件权限", context, lambda ctx, cancel, result, progress: backend.permission(ctx, cancel, result, progress, path, mode),
                  affected=(posixpath.dirname(path),), paths=(path,))

    def _paste(self, context, directory):
        provider = self.clipboard.provider
        if provider is not None and provider.paste_remote(self, context, directory):
            return
        value = self.clipboard.get(context.connection)
        if value is None:
            if provider is None and (self.clipboard.local_paths() or self.clipboard.get(context.connection, allow_other=True) is not None):
                self._prompt_file_bridge()
            return
        value.in_flight = True
        def preflighted(job, error):
            if error or self.clipboard.value is not value or not self.controller.current(context.connection):
                self.clipboard.finish(value)
                if error:
                    self._report_result(job, error)
                return
            plans, apply_all = [], None
            occupied = job.result["occupied"]
            for plan in job.result["plans"]:
                choice = apply_all or "replace"
                if plan.conflict and apply_all is None:
                    box = QMessageBox(self.workspace)
                    box.setWindowTitle(tr("文件已存在"))
                    box.setTextFormat(Qt.TextFormat.PlainText)
                    box.setText(tr("目标已存在：{0}", plan.target))
                    overwrite = box.addButton(tr("替换"), QMessageBox.ButtonRole.AcceptRole)
                    keep = box.addButton(tr("保留两个"), QMessageBox.ButtonRole.ActionRole)
                    skip = box.addButton(tr("跳过"), QMessageBox.ButtonRole.RejectRole)
                    box.addButton(tr("取消"), QMessageBox.ButtonRole.DestructiveRole)
                    check = QCheckBox(tr("对后续冲突执行此操作"))
                    box.setCheckBox(check)
                    box.exec()
                    clicked = box.clickedButton()
                    choice = "replace" if clicked is overwrite else "keep" if clicked is keep else "skip" if clicked is skip else "cancel"
                    if check.isChecked() and choice != "cancel":
                        apply_all = choice
                if choice == "cancel":
                    self.clipboard.finish(value)
                    return
                if plan.conflict and choice == "skip":
                    continue
                if plan.conflict and choice == "keep":
                    plan = replace(plan, target=backend.next_copy_name(plan.target, occupied), conflict=False)
                plans.append((plan, plan.conflict and choice == "replace"))
            if not plans or self.clipboard.value is not value:
                self.clipboard.finish(value)
                return
            def pasted(done, failure):
                self.clipboard.finish(value, done.result.get("completed_sources", ()))
                self._report_result(done, failure)
            affected = tuple(posixpath.dirname(path) for plan, _replace in plans for path in (plan.source, plan.target))
            started = self._run("移动" if value.cut else "复制", context,
                                lambda ctx, cancel, result, progress: backend.paste(ctx, cancel, result, progress, tuple(plans), value.cut),
                                affected=affected, callback=pasted, paths=value.paths)
            if started is None:
                self.clipboard.finish(value)
        started = self._run("检查粘贴目标", context, lambda ctx, cancel, result, progress: backend.paste_preflight(ctx, cancel, result, progress, value.paths, directory),
                            callback=preflighted, paths=value.paths)
        if started is None:
            self.clipboard.finish(value)

    def _update_cut(self):
        if self._closed:
            return
        value = self.clipboard.get(self._connection())
        self.workspace.remote.set_cut_paths(value.paths if value is not None and value.cut else ())

    def _edit(self, context, path):
        from ..editor.dialog import RemoteFileEditor
        key = (context.connection.connection_stop, path)
        editor = self._editors.get(key)
        if editor is None:
            editor = RemoteFileEditor(self.workspace._session, context.connection, path, self.workspace.window(), self.workspace._log_service)
            editor.directory_changed.connect(self.controller.directories_changed.emit)
            editor.destroyed.connect(lambda *_args, value=key: self._editors.pop(value, None))
            self._editors[key] = editor
        editor.show()
        editor.raise_()
        editor.activateWindow()

    def _command(self, action, context, path):
        quoted = shlex.quote(path)
        if action in {"script", "script_args"}:
            args = []
            if action == "script_args":
                value, accepted = QInputDialog.getText(self.workspace, tr("执行脚本"), tr("参数："))
                if not accepted:
                    return
                try:
                    args = shlex.split(value)
                except ValueError:
                    QMessageBox.warning(self.workspace, tr("执行脚本"), tr("参数格式错误"))
                    return
            shell = "zsh" if path.lower().endswith(".zsh") else "bash" if path.lower().endswith((".sh", ".bash")) else None
            command = (f"{shell} -- {quoted}" if shell else quoted) + (" " + shlex.join(args) if args else "")
            command = f"cd -- {shlex.quote(posixpath.dirname(path))} && {command}"
        elif action == "tail_follow":
            command = f"tail -f -- {quoted}"
        elif action == "tail_lines":
            count, accepted = QInputDialog.getInt(self.workspace, tr("查看日志"), tr("行数："), 100, 1, 1000000)
            if not accepted:
                return
            command = f"tail -n {count} -- {quoted}"
        else:
            keyword, accepted = QInputDialog.getText(self.workspace, tr("查询日志"), tr("关键字："))
            if not accepted or not keyword:
                return
            command = f"grep -nF -- {shlex.quote(keyword)} {quoted}"
        if any(ord(char) < 32 or ord(char) == 127 for char in command):
            QMessageBox.warning(self.workspace, tr("文件操作"), tr("参数不能包含控制字符"))
            return
        if self.controller.current(context.connection):
            self.command_requested.emit(command)

    def close_editors(self):
        return all(editor.close() for editor in list(self._editors.values()))

    def shutdown(self):
        self._closed = True
        if self._terminal_menu is not None:
            self._terminal_menu.shutdown()
        self.clipboard.changed.disconnect(self._update_cut)
        self.clipboard.status.disconnect(self._clipboard_status)
        for editor in list(self._editors.values()):
            editor.shutdown()
        for dialog in self._progress_dialogs.values():
            dialog.close()
            dialog.deleteLater()
        self._callbacks.clear()
