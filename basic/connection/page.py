"""Directory selection and local server configuration editing operations."""

from uuid import uuid4
import json

from PySide6.QtWidgets import QInputDialog, QMessageBox, QVBoxLayout
from PySide6.QtCore import Qt

from common.i18n import tr
from common.licensing.prompt import prompt_activation
from common.qt.module_page import ModulePage

from .form import ServerConfigurationForm
from .model import ServerConfiguration
from .server_picker import ServerPickerDialog
from .store import SERVER_SUFFIX, ServerConfigStore


class ConnectionPage(ModulePage):
    def __init__(self, store: ServerConfigStore) -> None:
        super().__init__()
        self.store = store
        self.current_name: str | None = None
        self._names: list[str] = []
        self._dirty = False
        self._saved_configuration = ServerConfiguration()
        self._shell_pages: dict[str, list[tuple[str, ModulePage]]] = {}
        self._retained_shell_pages: dict[ModulePage, tuple[str, str]] = {}
        self._shell_factory = None
        self._history_service = None
        self._authorization = None
        self.file_actions = {
            "new": self.create_configuration, "rename": self.rename_configuration,
            "copy": self.copy_configuration, "delete": self.delete_configuration,
            "save": self.save_configuration,
            "connect": self.open_shell,
            "history": self.open_history,
        }
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.form = ServerConfigurationForm()
        self.form.changed.connect(self._mark_dirty)
        self.form.path_connection_requested.connect(self.open_shell)
        self.form.password_visibility_button.clicked.connect(self.toggle_password_visibility)
        layout.addWidget(self.form, 1)

    def bind_registry(self, registry) -> None:
        super().bind_registry(registry)
        authorization = registry.get_service("authorization")
        if authorization is not self._authorization:
            if self._authorization is not None:
                self._authorization.changed.disconnect(self._password_authorization_changed)
            self._authorization = authorization
            if authorization is not None:
                authorization.changed.connect(self._password_authorization_changed)
        self.form.set_password_visibility_available(True)
        try:
            self._shell_factory = registry.get("shell").page_factory
        except KeyError:
            self._shell_factory = None
        self.form.set_connection_available(self._shell_factory is not None)
        self._bind_history_service()
        if self.store.log_service is not None:
            self.store.log_service.write_failed.connect(self._audit_write_failed, Qt.ConnectionType.QueuedConnection)
        self.actions_changed.emit()

    def activate(self) -> None:
        try:
            self._refresh_directory()
            if self.current_name not in self._names and not self._dirty:
                if self._names:
                    self.select_item(self._names[0])
                else:
                    self._clear_editor()
        except (OSError, ValueError) as exc:
            self._show_error(exc)

    def directory_items(self) -> list[tuple[str, str]]:
        return [(name, f"{name} *" if name == self.current_name and self._dirty else name) for name in self._names]

    def current_item_id(self) -> str | None:
        return self.current_name

    def select_item(self, item_id: str) -> bool:
        if item_id == self.current_name:
            return True
        if not self.can_leave():
            return False
        try:
            self._load_configuration(item_id)
        except (OSError, ValueError) as exc:
            self._show_error(exc)
            return False
        return True

    def activate_item(self, item_id: str) -> None:
        if self.select_item(item_id):
            self.open_shell()

    def is_action_enabled(self, action_id: str) -> bool:
        if action_id == "connect":
            return self._shell_factory is not None
        if action_id == "history":
            return self.current_name is not None
        if action_id == "new":
            return True
        if action_id == "save":
            return self._dirty
        return self.current_name is not None and action_id in self.file_actions

    def action_tooltip(self, action_id: str) -> str | None:
        if action_id == "history" and self.registry.get_service("history") is None:
            return tr("历史版本需要付费授权")
        return None

    def toggle_password_visibility(self) -> None:
        policy = self._password_policy()
        if policy is not None:
            policy.toggle(self.form.controls["PASSWORD"])
            self.form.update_password_visibility()
        else:
            self.form.hide_password()
            prompt_activation(self.registry, self, tr("密码显示"))

    def _password_policy(self):
        registry = getattr(self, "registry", None)
        return registry.get_service("password_visibility") if registry is not None else None

    def _password_authorization_changed(self) -> None:
        self.form.set_password_visibility_available(True)
        self._bind_history_service()
        self.actions_changed.emit()

    def _bind_history_service(self) -> None:
        self._history_service = self.registry.get_service("history")
        self.store.bind_services(self.registry.get_service("log"), self._history_service)
        if self._history_service is not None:
            self._history_service.bind_log(self.store.log_service)

    def open_history(self) -> None:
        self._bind_history_service()
        if self.current_name is None:
            return
        if self._history_service is None:
            prompt_activation(self.registry, self, tr("历史版本"))
            return
        if not self.can_leave():
            return
        try:
            self.store.ensure_history(self.current_name)
            resource = self.store.resource_id(self.current_name)
            service = self._history_service
            version_id = service.choose_version(
                resource, self.current_name, self.window(),
            )
            if version_id is None or self.registry.get_service("history") is not service:
                return
            version = service.read(resource, version_id)
            configuration = ServerConfiguration.from_document(json.loads(version.content))
            self.store.save(self.current_name, configuration, reason="回退")
            self._load_configuration(self.current_name)
            self._show_history_warning()
            self.status_changed.emit(tr("已恢复历史版本：{0}", version.created_at))
        except (OSError, ValueError) as exc:
            self._show_error(exc)

    def _show_history_warning(self) -> None:
        if self.store.last_history_error is not None:
            QMessageBox.warning(self, tr("历史版本"), tr("配置操作已完成，但历史版本保存失败：{0}", self.store.last_history_error))

    def _audit_write_failed(self, path, message: str) -> None:
        if path == self.store.last_audit_log_path:
            self.status_changed.emit(tr("配置日志写入失败：{0}", message))

    def can_leave(self) -> bool:
        if not self._dirty:
            return True
        answer = QMessageBox.question(
            self, tr("存在未保存内容"), tr("是否先保存当前文件？"),
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self.save_configuration()
        self.form.set_configuration(self._saved_configuration)
        self._dirty = False
        self._update_state()
        return True

    def create_configuration(self) -> None:
        if not self.can_leave():
            return
        name = self._ask_name(tr("新建"))
        if name is None:
            return
        try:
            self.store.create(name)
            self._load_configuration(name)
            self._refresh_directory()
            self._show_history_warning()
        except (OSError, ValueError) as exc:
            self._show_error(exc)

    def rename_configuration(self) -> None:
        if self.current_name is None or not self.can_leave():
            return
        name = self._ask_name(tr("重命名"), self.current_name)
        if name is None or name == self.current_name:
            return
        try:
            self.store.rename(self.current_name, name)
            shells = self._shell_pages.pop(self.current_name, None)
            if shells is not None:
                self._shell_pages[name] = shells
                for _panel_id, page in shells:
                    page.set_configuration(name, self._saved_configuration)
                    page.setWindowTitle(f"{name} Shell")
            for page, (panel_id, previous_name) in list(self._retained_shell_pages.items()):
                if previous_name == self.current_name:
                    self._retained_shell_pages[page] = (panel_id, name)
                    page.set_configuration(name, self._saved_configuration)
                    page.setWindowTitle(f"{name} Shell")
            self.current_name = name
            self._refresh_directory()
            self._update_state()
            self._show_history_warning()
        except (OSError, ValueError) as exc:
            self._show_error(exc)

    def copy_configuration(self) -> None:
        if self.current_name is None or not self.can_leave():
            return
        name = self._ask_name(tr("复制"), f"{self.current_name} - {tr('副本')}")
        if name is None:
            return
        try:
            self.store.copy(self.current_name, name)
            self._load_configuration(name)
            self._refresh_directory()
            self._show_history_warning()
        except (OSError, ValueError) as exc:
            self._show_error(exc)

    def delete_configuration(self) -> None:
        if self.current_name is None or not self.can_leave():
            return
        if QMessageBox.question(
            self, tr("删除"), tr("确定删除配置“{0}”吗？", self.current_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            self.store.delete(self.current_name)
            self._close_shell(self.current_name)
            self._clear_editor()
            self._refresh_directory()
            if self._names:
                self._load_configuration(self._names[0])
        except (OSError, ValueError) as exc:
            self._show_error(exc)

    def save_configuration(self, show_message: bool = True) -> bool:
        try:
            configuration = self.form.configuration()
            configuration.validate()
            name = self.current_name
            if name is None:
                name = self._ask_name(tr("保存"))
                if name is None:
                    return False
                self.store.create(name, configuration)
            else:
                self.store.save(name, configuration)
        except (OSError, ValueError) as exc:
            self._show_error(exc)
            return False
        self._saved_configuration = configuration
        self.current_name = name
        self._dirty = False
        self._refresh_directory()
        self._update_state()
        self.status_changed.emit(tr("已保存：{0}", self.current_name))
        self._show_history_warning()
        if show_message and self.store.last_history_error is None:
            QMessageBox.information(self, tr("保存"), tr("已保存：{0}", self.current_name))
        return True

    def open_shell(self, path_index: int | None = None) -> None:
        if self._shell_factory is None:
            return
        if (self.current_name is None or self._dirty) and not self.save_configuration(show_message=False):
            return

        name = self.current_name
        shells = self._shell_pages.get(name)
        cached = shells[0] if shells else self._create_shell_page(name)
        panel_id, page = cached
        page.set_configuration(name, self._saved_configuration)
        page.setWindowTitle(f"{name} Shell")
        self.bottom_panel_requested.emit(panel_id, page.windowTitle(), page)
        page.connect_selected(path_index)

    def open_workflow_shell(self, name, command="", *, directory=""):
        from basic.shell.profile import ShellProfile
        configuration = self.store.load(name)
        ShellProfile(name, configuration).validate()
        if self._shell_factory is None:
            raise ValueError(tr("命令终端不可用"))
        panel_id, page = self._create_shell_page(name)
        page.set_configuration(name, configuration)
        page.setWindowTitle(f"{name} Shell")
        self.bottom_panel_requested.emit(panel_id, page.windowTitle(), page)
        page.open_workflow_command(command, directory=directory)
        return page

    def _create_shell_page(self, name: str):
        page = self._shell_factory()
        page.bind_registry(self.registry)
        page.connection_requested.connect(lambda name, target=page: self._request_shell_connection(name, target))
        page.panel_focus_requested.connect(self.panel_focus_requested)
        page.bottom_panel_requested.connect(self.bottom_panel_requested)
        page.bottom_panel_removed.connect(self.bottom_panel_removed)
        page.close_requested.connect(lambda target=page: self._close_shell_page(target))
        page.new_panel_requested.connect(lambda target=page: self._choose_shell_configuration(target))
        page.duplicate_panel_requested.connect(lambda target=page: self._open_additional_shell(target))
        page.transfer_views_closed.connect(lambda target=page: self._release_retained_shell(target))
        cached = ("connection.shell." + uuid4().hex, page)
        self._shell_pages.setdefault(name, []).append(cached)
        return cached

    def _shell_name(self, source: ModulePage) -> str | None:
        retained = self._retained_shell_pages.get(source)
        if retained is not None:
            return retained[1]
        return next((name for name, shells in self._shell_pages.items() if any(page is source for _panel_id, page in shells)), None)

    def _choose_shell_configuration(self, source: ModulePage) -> None:
        if self._shell_factory is None:
            return
        try:
            names = self.store.list_names()
        except (OSError, ValueError) as exc:
            self._show_error(exc)
            return
        if not names:
            QMessageBox.information(self, tr("新建连接"), tr("请先保存服务器配置"))
            return
        current = self._shell_name(source)
        dialog = ServerPickerDialog(names, current, self)
        try:
            if dialog.exec() == ServerPickerDialog.DialogCode.Accepted:
                name = dialog.selected_name()
                if name is not None:
                    self._open_additional_shell(source, name)
        finally:
            dialog.deleteLater()

    def _open_additional_shell(self, source: ModulePage, name: str | None = None) -> None:
        name = name or self._shell_name(source)
        if name is None or self._shell_factory is None:
            return
        if name == self.current_name and self._dirty and not self.save_configuration(show_message=False):
            return
        try:
            configuration = self.store.load(name)
        except (OSError, ValueError) as exc:
            self._show_error(exc)
            return
        panel_id, page = self._create_shell_page(name)
        page.set_configuration(name, configuration)
        page.setWindowTitle(f"{name} Shell")
        self.bottom_panel_requested.emit(panel_id, page.windowTitle(), page)
        page.connect_selected()

    def _request_shell_connection(self, name: str, page: ModulePage) -> None:
        if name == self.current_name and self._dirty and not self.save_configuration(show_message=False):
            return
        try:
            configuration = self._saved_configuration if name == self.current_name else self.store.load(name)
            page.set_configuration(name, configuration)
            page.connect_selected()
        except (OSError, ValueError) as exc:
            self._show_error(exc)

    def _close_shell(self, name: str) -> None:
        for panel_id, page in self._shell_pages.pop(name, ()):
            page.shutdown()
            self.bottom_panel_removed.emit(panel_id)
            page.deleteLater()
        for page, (_panel_id, retained_name) in list(self._retained_shell_pages.items()):
            if retained_name == name:
                self._retained_shell_pages.pop(page)
                page.shutdown()
                page.deleteLater()

    def _release_retained_shell(self, page: ModulePage) -> None:
        if page in self._retained_shell_pages and not page.has_transfer_views():
            self._retained_shell_pages.pop(page)
            page.shutdown()
            page.deleteLater()

    def _close_shell_page(self, page: ModulePage) -> None:
        can_close = getattr(page, "can_close", None)
        retain = page.has_transfer_views()
        if not retain and callable(can_close) and not can_close():
            return
        for name, shells in list(self._shell_pages.items()):
            for cached in tuple(shells):
                panel_id, target = cached
                if target is page:
                    shells.remove(cached)
                    if not shells:
                        del self._shell_pages[name]
                    if retain:
                        self._retained_shell_pages[page] = (panel_id, name)
                    else:
                        page.shutdown()
                    self.bottom_panel_removed.emit(panel_id)
                    if not retain:
                        page.deleteLater()
                    return

    def can_close(self) -> bool:
        pages = [page for shells in self._shell_pages.values() for _panel_id, page in shells]
        return all(not callable(getattr(page, "can_close", None)) or page.can_close() for page in (*pages, *self._retained_shell_pages))

    def _ask_name(self, title: str, default: str = "") -> str | None:
        name, accepted = QInputDialog.getText(self, title, tr("配置名称："), text=default)
        if not accepted:
            return None
        name = name.strip()
        if name.lower().endswith(SERVER_SUFFIX):
            name = name[:-len(SERVER_SUFFIX)]
        if not name:
            self._show_error(ValueError(tr("文件名称不能为空")))
            return None
        return name

    def _load_configuration(self, name: str) -> None:
        configuration = self.store.load(name)
        self.current_name = name
        self._saved_configuration = configuration
        self.form.set_configuration(configuration)
        self.form.setEnabled(True)
        self._dirty = False
        self._update_state()
        self.status_changed.emit(tr("已加载：{0}", name))

    def _clear_editor(self) -> None:
        self.current_name = None
        self._saved_configuration = ServerConfiguration()
        self.form.set_configuration(self._saved_configuration)
        self.form.setEnabled(True)
        self._dirty = False
        self._update_state()

    def _refresh_directory(self) -> None:
        self._names = self.store.list_names()
        for name in set(self._shell_pages) | {name for _panel_id, name in self._retained_shell_pages.values()}:
            if name not in self._names:
                self._close_shell(name)
        self.directory_changed.emit()

    def _mark_dirty(self) -> None:
        if not self._dirty:
            self._dirty = True
            self._update_state()

    def _update_state(self) -> None:
        self.directory_changed.emit()
        self.actions_changed.emit()

    def _show_error(self, error: Exception) -> None:
        QMessageBox.critical(self, tr("操作失败"), str(error))
