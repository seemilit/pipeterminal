"""Basic task page integrated with the shared application shell."""

import json
from copy import deepcopy
from uuid import uuid4

from PySide6.QtCore import QEvent, QSignalBlocker, QTimer, Qt
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QInputDialog, QMenu, QMessageBox, QPlainTextEdit, QScrollArea, QSplitter, QStackedLayout, QVBoxLayout, QWidget

from common.i18n import tr
from common.i18n.errors import error_message
from common.licensing.prompt import prompt_activation
from common.i18n.widgets import QAction, QDialog, QLabel, QLineEdit, QPushButton, QTabWidget, QTreeWidget, QTreeWidgetItem
from common.qt.document_history import open_document_history
from common.qt.module_page import ModulePage
from common.settings.store import SettingsStore

from .edit_history import EditHistory
from .environment import environment_issue, local_interpreter
from .history import STATES, RunHistoryDialog, RunHistoryStore
from .validation import prepare_workflow
from .graph import (
    PARALLEL_REQUIRED, START, WorkflowUpgradeRequired, append_node, ensure_graph,
    execution_plan, graph_structure, remove_node, validate_connection,
)
from .store import TASK_SUFFIX, TaskStore
from .schema import STEP_LABELS, node_display_name
from .run_manager import TaskRunManager
from .run_page import TaskExecutionPage, TaskRunPage
from .views import ModuleLibrary, TaskFlowView, parameter_summary
from .parameters import TaskParameterEditor
from .schema import CATEGORIES
from .execution.schema import STEP_LABELS as EXECUTION_LABELS, effective_kind
from .execution.connections import ExecutionServices


class TaskPage(ModulePage):
    uses_panel_workspace = False

    def __init__(self, store: TaskStore) -> None:
        super().__init__()
        self.store = store
        self._preferences = SettingsStore(store.directory.parent / "settings.json")
        try:
            visible = self._preferences.read_section("task").get("library_visible", True)
        except (OSError, ValueError):
            visible = True
        self._library_visible = visible if isinstance(visible, bool) else True
        self.current_name: str | None = None
        self._names: list[str] = []
        self._document: dict | None = None
        self._dirty = False
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._autosave_timer.setInterval(1000)
        self._autosave_timer.timeout.connect(self._autosave)
        self._runs = {}
        self._selected_runs: dict[str, str] = {}
        self._edit_history = EditHistory()
        self._saved_document = None
        self._history_store = RunHistoryStore(store.directory.parent / "task_history")
        self._history_failure_ids = set()
        self._views_ready = False
        self.execution_services = ExecutionServices(store.directory.parent, self)
        self.execution_services.trust_requested.connect(self._confirm_task_host)
        self._artifacts = {}
        self.file_actions = {
            "new": self.create_task, "rename": self.rename_task,
            "copy": self.copy_task, "delete": self.delete_task, "save": self.save_task,
            "execute": self.execute_task, "stop": self._choose_run_to_stop, "history": self.open_history,
            "log": self._open_run_history,
        }
        self.setObjectName("taskEditor")
        self._editor_run_page = None
        self._page_stack = QStackedLayout(self)
        self._editor_view = QWidget()
        self._page_stack.addWidget(self._editor_view)
        layout = QVBoxLayout(self._editor_view)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(16)
        header = QHBoxLayout()
        self.title = QLabel(tr("任务"))
        self.title.setObjectName("taskHeading")
        header.addWidget(self.title)
        header.addStretch()
        self.notice = QLabel(tr("暂无任务"))
        self.notice.setObjectName("taskMetadata")
        header.addWidget(self.notice)
        self.execute_button = QPushButton(tr("执行"))
        self.execute_button.setObjectName("taskExecuteButton")
        self.execute_button.clicked.connect(lambda: self.execute_task())
        header.addWidget(self.execute_button)
        layout.addLayout(header)
        bar_widget = QFrame()
        bar_widget.setObjectName("taskToolBar")
        bar_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        bar = QHBoxLayout(bar_widget)
        bar.setContentsMargins(8, 4, 8, 4)
        bar.setSpacing(4)
        self.add_step = QPushButton(tr("添加流程"))
        menu = QMenu(self.add_step)
        menu.aboutToShow.connect(self._refresh_node_environment)
        self._node_actions = {}
        for category, kinds in CATEGORIES.items():
            category_menu = QMenu(menu)
            category_menu.setToolTipsVisible(True)
            category_action = QAction(tr(category), menu)
            category_action.setMenu(category_menu)
            menu.addAction(category_action)
            for step_type in kinds:
                action = QAction(tr(STEP_LABELS[step_type]), category_menu)
                action.triggered.connect(lambda _checked=False, kind=step_type: self._add_step(step_type=kind))
                category_menu.addAction(action)
                self._node_actions[step_type] = action
        self.add_step.setMenu(menu)
        bar.addWidget(self.add_step)
        self.step_buttons = []
        for label, action in (("修改", self._edit_step), ("复制", self._copy_step), ("删除", self._remove_step)):
            button = QPushButton(tr(label))
            button.clicked.connect(lambda _checked=False, handler=action: handler())
            bar.addWidget(button)
            self.step_buttons.append(button)
        self.arrange_button = QPushButton(tr("自动排列"))
        self.arrange_button.clicked.connect(lambda: self._arrange_steps())
        bar.addWidget(self.arrange_button)
        history_button = QPushButton(tr("执行记录"))
        history_button.clicked.connect(self._open_run_history)
        bar.addWidget(history_button)
        bar.addStretch()
        self.library_button = QPushButton(tr("模块库"))
        self.library_button.setCheckable(True)
        self.library_button.setChecked(self._library_visible)
        self.library_button.toggled.connect(self._toggle_library)
        bar.addWidget(self.library_button)
        self.flow_button = QPushButton(tr("视图窗"))
        self.parameter_button = QPushButton(tr("参数窗"))
        for button in (self.flow_button, self.parameter_button):
            button.setCheckable(True)
            button.setMinimumWidth(72)
            button.setChecked(True)
            button.toggled.connect(self._sync_views)
            bar.addWidget(button)
        layout.addWidget(bar_widget)
        self.undo_notice = QLabel(tr("流程内容超过撤销内存上限，部分操作将无法撤销或重做。"))
        self.undo_notice.setWordWrap(True)
        self.undo_notice.hide()
        layout.addWidget(self.undo_notice)
        self.steps = QTreeWidget(self)
        self.steps.hide()
        self.steps.setRootIsDecorated(False)
        self.steps.setHeaderLabels([tr("流程"), tr("目标分支")])
        self.steps.itemDoubleClicked.connect(lambda _item, _column: self._edit_step())
        self.steps.itemSelectionChanged.connect(self._update_step_actions)
        self.steps.itemSelectionChanged.connect(self._select_step_view)
        self.flow = TaskFlowView(self)
        self.flow.show_missing_parameters = True
        self.flow.accept_empty_module_drop = True
        self.flow.module_unavailable = self._refresh_node_environment
        self.flow.step_selected.connect(self._select_flow_step)
        self.flow.step_activated.connect(self._edit_step)
        self.flow.position_changed.connect(self._position_step)
        self.flow.connection_requested.connect(self._connect_steps)
        self.flow.connection_allowed = self._can_connect_steps
        self.flow.module_dropped.connect(self._insert_module)
        self.flow.module_add_requested.connect(self._add_from_arrow)
        self.flow.node_copy_requested.connect(lambda index: self._copy_step(index))
        self.flow.node_delete_requested.connect(self._remove_steps)
        self.flow.run_from_requested.connect(self._execute_from_step)
        self.flow.run_only_requested.connect(self._execute_selected_steps)
        self.flow.edge_delete_requested.connect(self._disconnect_step)
        self.flow.edge_insert_requested.connect(self._insert_on_edge)
        self.flow.undo_requested.connect(self._restore_edit)
        self.flow.redo_requested.connect(lambda: self._restore_edit(True))
        self._refresh_flow_tooltip()
        self.parameters = TaskParameterEditor(services=self.execution_services)
        self.parameters.changed.connect(self._parameters_changed)
        self.parameters.name_changed.connect(self._node_name_changed)
        self.library = ModuleLibrary()
        self.library_panel = self._view_panel(tr("模块库"), self.library)
        self.library_search = QLineEdit()
        self.library_search.setPlaceholderText(tr("搜索"))
        self.library_search.setClearButtonEnabled(True)
        self.library_search.textChanged.connect(self.library.filter_modules)
        self.library_panel.layout().insertWidget(1, self.library_search)
        self.flow_panel = self._view_panel(tr("流程视图"), self.flow)
        self.parameter_preview = QPlainTextEdit()
        self.parameter_preview.setObjectName("taskParameterPreview")
        self.parameter_preview.setReadOnly(True)
        self.parameter_tabs = QTabWidget()
        self.parameter_tabs.setObjectName("taskParameterTabs")
        self.parameter_tabs.addTab(self.parameters, tr("编辑参数"))
        self.parameter_tabs.addTab(self.parameter_preview, tr("流程参数"))
        self.parameter_panel = QFrame()
        self.parameter_panel.setObjectName("taskPanel")
        self.parameter_panel.setFrameShape(QFrame.Shape.StyledPanel)
        inspector_layout = QVBoxLayout(self.parameter_panel)
        inspector_layout.setContentsMargins(12, 10, 12, 12)
        inspector_layout.setSpacing(10)
        self.inspector_title = QLabel(tr("任务"))
        self.inspector_title.setTextFormat(Qt.TextFormat.PlainText)
        self.inspector_title.setObjectName("panelHeading")
        self.inspector_title.setWordWrap(True)
        inspector_layout.addWidget(self.inspector_title)
        self.task_overview = QLabel()
        self.task_overview.setWordWrap(True)
        self.task_overview.setAlignment(Qt.AlignmentFlag.AlignTop)
        inspector_layout.addWidget(self.task_overview)
        inspector_layout.addWidget(self.parameter_tabs, 1)
        self.editor_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.editor_splitter.setChildrenCollapsible(False)
        self.editor_splitter.setHandleWidth(8)
        self.editor_splitter.addWidget(self.library_panel)
        self.editor_splitter.addWidget(self.flow_panel)
        self.editor_splitter.addWidget(self.parameter_panel)
        self.editor_splitter.setStretchFactor(0, 0)
        self.editor_splitter.setStretchFactor(1, 2)
        self.editor_splitter.setStretchFactor(2, 0)
        self.editor_splitter.setSizes([220, 760, 340])
        layout.addWidget(self.editor_splitter, 1)
        self.library_panel.setVisible(self._library_visible)
        self._views_ready = True
        self.new_panel_requested.connect(self.create_task)
        self._update_state()

    def bind_registry(self, registry):
        super().bind_registry(registry)
        self.store.history_service = lambda: registry.get_service("history")
        self.run_manager = registry.get_service("task_runs")
        if self.run_manager is None:
            self.run_manager = TaskRunManager(self.store.directory.parent, registry, self.window())
            registry.register_service("task_runs", self.run_manager)
        self._runs = self.run_manager.runs
        self._history_store = self.run_manager.store
        self._history_writer = self.run_manager.writer
        self.run_manager.history_failed.connect(self._history_write_failed)
        self.run_manager.changed.connect(self._run_changed)
        self.execution_services.log_service = registry.get_service("log")
        appearance = registry.get_service("window_appearance")
        if appearance is not None:
            appearance.decorate_task(self)

    def _confirm_task_host(self, request):
        try:
            request["accepted"] = QMessageBox.question(self, tr("确认服务器主机密钥"), tr("服务器：{0}\n密钥类型：{1}\n指纹：{2}\n是否信任并保存？", request["host"], request["kind"], request["fingerprint"]), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
        finally:
            request["event"].set()

    def activate(self) -> None:
        self.activate_with_selection(None)

    def activate_with_selection(self, item_id) -> None:
        try:
            self._refresh_node_environment()
            self._refresh_directory()
            if item_id in self._names and item_id != self.current_name:
                self.select_item(item_id)
                return
            if self.current_name not in self._names:
                if self._names:
                    self._load_task(self._names[0])
                    return
                self.current_name = None
                self._document = None
                self._dirty = False
                self._populate_steps()
            self._update_state()
        except (OSError, ValueError) as exc:
            self._show_error(exc)

    def directory_items(self) -> list[tuple[str, str]]:
        return [(name, f"{name} *" if name == self.current_name and self._dirty else name) for name in self._names]

    def activate_item(self, item_id: str) -> None:
        self.open_execution_page(item_id)

    def workspace_item_actions(self, item_id: str):
        def copy():
            if self.select_item(item_id):
                self.copy_task()

        return (("复制", copy, True),)

    def open_execution_page(self, name: str) -> None:
        try:
            document = deepcopy(self._document) if name == self.current_name else self.store.load(name)
            legacy = "links" not in document
            ensure_graph(document)
        except (OSError, ValueError) as error:
            self._show_error(error)
            return

        def execute(**options):
            self._execute_named_task(
                page.workspace_item_id, preview=page, source=page.document, legacy=legacy, **options,
            )

        page = TaskExecutionPage(name, document, execute)
        panel_id = f"execute.{uuid4().hex}"

        def close():
            if page.run_page is not None and not page.run_page.can_hide():
                return
            self.bottom_panel_removed.emit(panel_id)
            if page.run is None or not page.run.active:
                page.deleteLater()

        def open_new_tab():
            self.open_execution_page(page.workspace_item_id)

        page.close_requested.connect(close)
        page.new_panel_requested.connect(open_new_tab)
        page.duplicate_panel_requested.connect(open_new_tab)
        self.bottom_panel_requested.emit(panel_id, page.windowTitle(), page)

    def current_item_id(self) -> str | None:
        return self.current_name

    def select_item(self, item_id: str) -> bool:
        if item_id == self.current_name:
            return True
        if not self.can_leave():
            return False
        try:
            self._load_task(item_id)
        except (OSError, ValueError) as exc:
            self._show_error(exc)
            return False
        self._page_stack.setCurrentWidget(self._editor_view)
        return True

    def is_action_enabled(self, action_id: str) -> bool:
        if action_id == "stop":
            return any(run.active and not run.runner.stop.is_set() for run in self._runs.values())
        if action_id == "execute":
            return self._document is not None and bool(self._document["steps"])
        return action_id == "new" or (self.current_name is not None and action_id in self.file_actions)

    def action_label(self, action_id: str) -> str | None:
        return tr("执行记录") if action_id == "log" else None

    def action_tooltip(self, action_id: str) -> str | None:
        if action_id == "history" and self.store.history_service() is None:
            return tr("历史版本需要付费授权")
        return None

    def open_history(self) -> None:
        try:
            open_document_history(
                self, self.current_name, self.store, self._restore_history, preview=self._preview_history,
            )
        except (OSError, ValueError) as error:
            self._show_error(error)

    def _restore_history(self, name: str, content: str) -> None:
        document = json.loads(content)
        self.store.validate(document)
        ensure_graph(document)
        self.store.save(name, document, reason="回退")
        self._load_task(name)
        self._show_version_warning()

    @staticmethod
    def _preview_history(content: str) -> str:
        document = json.loads(content)
        TaskStore.validate(document)
        ensure_graph(document)
        steps = document["steps"]
        if not steps:
            return str(tr("任务为空或包含尚未支持的流程"))
        names = {START: str(tr("开始"))}
        names.update(
            (step["node_id"], str(tr("{0}. {1}", index, node_display_name(step))))
            for index, step in enumerate(steps, 1)
        )
        links = "\n".join(f"{names[source]} → {names[target]}" for source, target, _, _ in document["links"])
        return "\n\n".join(part for part in (links, parameter_summary(steps)) if part)

    def _show_version_warning(self) -> None:
        if self.store.last_history_error is not None:
            self.status_changed.emit(tr("任务已保存，但历史版本保存失败：{0}", self.store.last_history_error))

    def create_task(self) -> None:
        if not self.can_leave():
            return
        name = self._ask_name(tr("新建"))
        if name is not None:
            self._change("create", name)

    def rename_task(self) -> None:
        if self.current_name is None or not self.can_leave():
            return
        name = self._ask_name(tr("重命名"), self.current_name)
        if name is not None and name != self.current_name:
            self._change("rename", self.current_name, name)

    def copy_task(self) -> None:
        if self.current_name is None or not self.can_leave():
            return
        name = self._ask_name(tr("复制"), f"{self.current_name} - {tr('副本')}")
        if name is not None:
            self._change("copy", self.current_name, name)

    def delete_task(self) -> None:
        if self.current_name is None or not self.can_leave():
            return
        if any(run.active and run.task_name == self.current_name for run in self.run_manager.runs.values()):
            QMessageBox.information(self, tr("任务"), tr("任务正在执行，请等待完成"))
            return
        if QMessageBox.question(
            self, tr("删除"), tr("确定删除任务“{0}”吗？", self.current_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes:
            self._change("delete", self.current_name)

    def save_task(self, show_message: bool = True, *, automatic: bool = False) -> bool:
        if self.current_name is None or self._document is None:
            return False
        self._autosave_timer.stop()
        try:
            self.store.save(self.current_name, self._document, reason="自动保存" if automatic else "保存")
        except (OSError, ValueError) as exc:
            if automatic:
                self.status_changed.emit(f"{tr('保存失败')} · {error_message(exc)}")
            else:
                self._show_error(exc)
            return False
        self._dirty = False
        self._saved_document = deepcopy(self._document)
        self._update_state()
        self.status_changed.emit(tr("已保存：{0}", self.current_name))
        self._show_version_warning()
        if show_message:
            message = (
                tr("任务已保存，但历史版本保存失败：{0}", self.store.last_history_error)
                if self.store.last_history_error is not None else tr("已保存：{0}", self.current_name)
            )
            QMessageBox.information(self, tr("保存"), message)
        return True

    def _autosave(self):
        if self._dirty:
            return self.save_task(show_message=False, automatic=True)
        return True

    def _schedule_autosave(self):
        if self._dirty:
            self._autosave_timer.start()
        else:
            self._autosave_timer.stop()

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._autosave_timer.isActive():
            self._autosave()

    def _change(self, operation: str, *names: str) -> None:
        try:
            getattr(self.store, operation)(*names)
            if operation == "delete":
                self._selected_runs.pop(names[0], None)
                self.current_name = None
                self._document = None
                self._dirty = False
                self._populate_steps()
            elif operation == "rename":
                for run in self._runs.values():
                    if run.task_name == names[0]:
                        run.task_name = names[1]
                if names[0] in self._selected_runs:
                    self._selected_runs[names[1]] = self._selected_runs.pop(names[0])
                self.directory_item_renamed.emit(*names)
            self._refresh_directory()
            selected = next(iter(self._names), None) if operation == "delete" else names[-1]
            if selected is not None:
                self._load_task(selected)
            else:
                self._update_state()
            self._show_version_warning()
        except (OSError, ValueError) as exc:
            self._update_state()
            self._show_error(exc)

    def _ask_name(self, title: str, default: str = "") -> str | None:
        name, accepted = QInputDialog.getText(self, title, tr("任务名称："), text=default)
        if not accepted:
            return None
        name = name.strip()
        if name.lower().endswith(TASK_SUFFIX):
            name = name[:-len(TASK_SUFFIX)]
        if not name:
            self._show_error(ValueError(tr("文件名称不能为空")))
            return None
        return name

    def _load_task(self, name: str, *, selected=None) -> None:
        document = self.store.load(name)
        ensure_graph(document)
        self._autosave_timer.stop()
        self._artifacts = {}
        self._edit_history.reset()
        self.undo_notice.hide()
        self.flow.set_validation_issues([])
        self._saved_document = deepcopy(document)
        self.current_name, self._document = name, document
        self._dirty = False
        self._populate_steps(selected)
        self._update_state()
        self.flow.center_flow()

    def _refresh_directory(self) -> None:
        names = self.store.list_names()
        changed = names != self._names
        self._names = names
        self.directory_changed.emit()
        if changed:
            self.workspace_directory_changed.emit()

    def _update_state(self) -> None:
        self._refresh_artifacts()
        self.title.setText(self.current_name if self.current_name is not None else tr("任务"))
        self.setWindowTitle(self.title.text() + (" *" if self._dirty else ""))
        self.notice.setText(tr("步骤数量：{0}", len(self._document["steps"])) if self._document is not None else tr("暂无任务"))
        self.execute_button.setEnabled(self.is_action_enabled("execute"))
        editable = self._document is not None
        self.add_step.setEnabled(editable)
        self.flow.set_editable(editable)
        self.flow.parallel_enabled = editable and self._parallel_scheduler() is not None
        self.parameters.form_widget.setEnabled(editable)
        self.parameters.execution.setEnabled(editable)
        self.parameters.upload.setEnabled(editable)
        self.parameters.wait.setEnabled(editable)
        self.parameters.health.setEnabled(editable)
        self.parameters.shell_panel.setEnabled(editable)
        self.arrange_button.setEnabled(editable)
        self._update_step_actions()
        entries = self._document["steps"] if self._document is not None else []
        item = self.steps.currentItem()
        index = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        self._refresh_parameter_preview(entries, index)
        self.directory_changed.emit()
        self.actions_changed.emit()

    def _populate_steps(self, selected=None):
        self.flow.clear_states()
        entries = self._document["steps"] if self._document is not None else []
        blocker = QSignalBlocker(self.steps)
        self.steps.clear()
        for index, step in enumerate(entries):
            item = QTreeWidgetItem([tr("{0}. {1}", index + 1, node_display_name(step)), str(step.get("properties", {}).get("TARGET_BRANCH", ""))])
            item.setData(0, Qt.ItemDataRole.UserRole, index)
            self.steps.addTopLevelItem(item)
            if selected == index:
                self.steps.setCurrentItem(item)
        del blocker
        self._refresh_views()
        self._update_step_actions()

    def _toggle_library(self, visible):
        self._library_visible = visible
        self.library_panel.setVisible(visible)
        try:
            self._preferences.update_section("task", {"library_visible": visible})
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, tr("保存失败"), tr("保存模块库显示状态失败：{0}", error_message(error)))

    def _sync_views(self, *_args):
        if not self._views_ready:
            return
        selected = self.steps.currentItem() is not None
        show_parameters = selected and self.parameter_button.isChecked()
        if not self.flow_button.isChecked() and not show_parameters:
            with QSignalBlocker(self.flow_button):
                self.flow_button.setChecked(True)
        self.flow_panel.setVisible(self.flow_button.isChecked())
        self.parameter_button.setEnabled(selected)
        self.parameter_panel.setVisible(show_parameters)

    def _view_panel(self, title, view):
        panel = QFrame()
        panel.setObjectName("taskPanel")
        panel.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(10)
        heading = QLabel(title)
        heading.setObjectName("panelHeading")
        layout.addWidget(heading)
        view.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(view, 1)
        return panel

    def _select_flow_step(self, index):
        item = self.steps.topLevelItem(index)
        blocker = QSignalBlocker(self.steps)
        self.steps.setCurrentItem(item)
        if item is None:
            self.steps.clearSelection()
        del blocker
        if item is not None:
            self.parameter_button.setChecked(True)
        self._select_step_view(sync_flow=False)
        self._update_step_actions()

    def _select_step_view(self, *, sync_flow=True):
        if not self._views_ready:
            return
        item = self.steps.currentItem()
        index = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else -1
        if sync_flow:
            self.flow.select_step(index)
        entries = self._document["steps"] if self._document is not None else []
        self.parameters.upload.artifact_options = self._preceding_artifacts(index)
        self.parameters.upload.artifact_results = self._artifacts
        self.parameters.display_step(entries[index] if index is not None and 0 <= index < len(entries) else None, True)
        self._refresh_parameter_preview(entries, index)

    def _refresh_views(self):
        if not self._views_ready:
            return
        entries = self._document["steps"] if self._document is not None else []
        item = self.steps.currentItem()
        index = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        self.flow.display_steps(entries, index, graph=self._document)
        self.parameters.upload.artifact_options = self._preceding_artifacts(index)
        self.parameters.upload.artifact_results = self._artifacts
        self.parameters.display_step(entries[index] if index is not None and 0 <= index < len(entries) else None, True)
        self._refresh_parameter_preview(entries, index)

    def _refresh_parameter_preview(self, entries, index):
        selected = index is not None and 0 <= index < len(entries)
        if selected:
            step = entries[index]
            self.inspector_title.setText(tr("{0}. {1}", index + 1, node_display_name(step)))
        else:
            self.inspector_title.setText(self.current_name or tr("任务"))
            self.task_overview.setText(tr("步骤数量：{0}", len(entries)) if self._document is not None else tr("暂无任务"))
        data = parameter_summary(entries, index) if selected else ""
        if self.parameter_preview.toPlainText() != data:
            self.parameter_preview.setPlainText(data)
        self.parameter_tabs.setTabVisible(0, selected)
        self.parameter_tabs.setTabVisible(1, not selected)
        self.parameter_tabs.setCurrentWidget(self.parameters if selected else self.parameter_preview)
        self.parameter_tabs.setVisible(bool(entries))
        self.task_overview.setVisible(not selected)
        self._sync_views()

    def _refresh_flow_tooltip(self):
        self.flow.setToolTip(
            tr("拖动节点自由摆放；从任一方向的圆点拖向另一节点连接下一步；Ctrl＋滚轮缩放；拖动空白处移动画布")
            + "\n" + tr("按住 Ctrl 单击可多选节点") + "\n" + tr("点击四向箭头添加并连接节点")
        )

    def changeEvent(self, event):
        super().changeEvent(event)
        if not getattr(self, "_views_ready", False):
            return
        if event.type() == QEvent.Type.LanguageChange:
            self._refresh_flow_tooltip()
            self._refresh_views()
        elif event.type() == QEvent.Type.PaletteChange:
            self._refresh_views()

    def _update_step_actions(self):
        item = self.steps.currentItem()
        index = self.steps.indexOfTopLevelItem(item) if item is not None else -1
        enabled = index >= 0
        for button in self.step_buttons:
            button.setEnabled(enabled)
        if enabled:
            self.step_buttons[0].setEnabled(self._document["steps"][index]["type"] in STEP_LABELS)

    def _preceding_artifacts(self, index):
        if self._document is None or index is None or index < 0:
            return []
        ids, _outgoing, incoming = graph_structure(self._document)
        node = ids[index]
        found = set()
        pending = list(incoming[node])
        while pending:
            ancestor = pending.pop()
            if ancestor != START and ancestor not in found:
                found.add(ancestor)
                pending.extend(incoming[ancestor])
        return [
            (step.get("properties", {}).get("ARTIFACT_NAME", "artifact").strip(),
             step.get("properties", {}).get("PROJECT_PATH", ""))
            for step in self._document["steps"]
            if step["node_id"] in found and step["type"] == "MAVEN_BUILD"
        ]

    def _parallel_scheduler(self):
        return self.registry.get_service("workflow_parallel")

    def _default_add_source(self):
        ids, outgoing, _incoming = graph_structure(self._document)
        return next((index for index in range(len(ids) - 1, -1, -1) if not outgoing[ids[index]]), -1)

    def _refresh_node_environment(self):
        try:
            servers = set(self.execution_services.store.list_names())
        except (OSError, ValueError):
            servers = set()
        issues = {
            kind: issue for kind in self._node_actions
            if (issue := environment_issue(kind, servers=servers))
        }
        for kind, action in self._node_actions.items():
            issue = issues.get(kind)
            action.setEnabled(not issue)
            action.setToolTip(issue or tr(STEP_LABELS[kind]))
        self.library.set_environment_issues(issues)
        return issues

    def _check_node_limit(self):
        limit = 5
        if len(self._document["steps"]) >= limit and self._parallel_scheduler() is None:
            raise WorkflowUpgradeRequired(tr("免费版每个流程最多添加 {0} 个节点，增加更多节点需要付费授权", limit))

    def _insert_connected_node(self, step, source_index, direction, replace_link=None):
        self._check_node_limit()
        issue = self._refresh_node_environment().get(step["type"])
        if issue:
            raise ValueError(issue)
        steps = self._document["steps"]
        source = START if source_index == -1 else steps[source_index]["node_id"]
        incoming = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}[direction]
        links = self._document["links"]
        existing = [link for link in links if link[0] == source]
        insert_inline = replace_link is not None or self._parallel_scheduler() is None and bool(existing)
        if self._parallel_scheduler() is None and len(existing) > 1:
            raise WorkflowUpgradeRequired(tr(PARALLEL_REQUIRED))
        if replace_link is not None and replace_link not in existing:
            raise ValueError(tr("连线已变化，请重新选择"))
        self._remember_edit()
        if insert_inline:
            old = replace_link if replace_link is not None else existing[0]
            links.remove(old)
            append_node(self._document, step, source, direction, incoming)
            links.append([step["node_id"], old[1], "", old[3]])
        else:
            append_node(self._document, step, source, direction, incoming)

    def _add_from_arrow(self, index, direction, kind):
        self._add_step(source_index=index, direction=direction, step_type=kind)

    def _insert_on_edge(self, endpoints, kind):
        if self._document is None:
            return
        link = next((link for link in self._document["links"] if tuple(link[:2]) == endpoints), None)
        if link is None:
            return
        source_index = -1 if link[0] == START else next(index for index, step in enumerate(self._document["steps"]) if step["node_id"] == link[0])
        direction = self.flow.edge_output_port(endpoints)
        position = self.flow.insertion_position(endpoints, source_index, direction)
        self._add_step(source_index=source_index, direction=direction, step_type=kind, position=position, replace_link=list(link))

    def _edit_step(self):
        if self._document is None or self.steps.currentItem() is None:
            return
        self.parameter_button.setChecked(True)
        self.parameter_tabs.setCurrentWidget(self.parameters)

    def _add_step(self, *, step_type, source_index=None, direction="bottom", position=None, replace_link=None):
        if self._document is None or step_type not in STEP_LABELS:
            return
        if source_index is None:
            source_index = self._default_add_source()
        index = len(self._document["steps"])
        if position is None:
            position = self.flow.next_module_position(source_index, direction)
        step = self._new_step(step_type, position)
        try:
            self._insert_connected_node(step, source_index, direction, replace_link)
        except ValueError as error:
            self._show_error(error)
            return
        self._dirty = True
        self._populate_steps(index)
        step["properties"].update(self.parameters.values())
        self._edit_step()
        if not self._autosave():
            self._update_state()

    @staticmethod
    def _new_step(step_type, position):
        properties = {}
        if step_type.startswith("REMOTE_"):
            properties["INTERPRETER"] = "sh"
        elif step_type.startswith("LOCAL_"):
            properties["INTERPRETER"] = local_interpreter() or "powershell"
        return {
            "type": step_type,
            "properties": properties,
            "position": position,
        }

    def _remove_step(self, index=None):
        if self._document is None:
            return
        if index is None:
            item = self.steps.currentItem()
            if item is None:
                return
            index = item.data(0, Qt.ItemDataRole.UserRole)
        self._remove_steps((index,))

    def _remove_steps(self, indexes):
        if self._document is None:
            return
        steps = self._document["steps"]
        indexes = sorted({index for index in indexes if 0 <= index < len(steps)}, reverse=True)
        if not indexes:
            return
        self._remember_edit()
        for index in indexes:
            remove_node(self._document, index)
        self._dirty = True
        self._populate_steps(min(indexes[-1], len(steps) - 1))
        self._schedule_autosave()
        self._update_state()

    def _position_step(self, index, position):
        if self._document is None:
            return
        if -1 <= index < len(self._document["steps"]):
            self._remember_edit()
            if index == -1:
                self._document["start_position"] = position
            else:
                self._document["steps"][index]["position"] = position
            self._dirty = True
            self._schedule_autosave()
            self._update_state()

    def _can_connect_steps(self, source, target):
        if self._document is None or source == target:
            return False
        steps = self._document["steps"]
        if not -1 <= source < len(steps) or not 0 <= target < len(steps):
            return False
        source_id = START if source == -1 else steps[source]["node_id"]
        target_id = steps[target]["node_id"]
        if any(link[:2] == [source_id, target_id] for link in self._document["links"]):
            return True
        try:
            validate_connection(self._document, source_id, target_id, self._parallel_scheduler() is not None)
        except ValueError:
            return False
        return True

    def _connect_steps(self, source, target, output_port, input_port):
        if self._document is None or source == target:
            return
        steps = self._document["steps"]
        source_id = START if source == -1 else steps[source]["node_id"]
        target_id = steps[target]["node_id"]
        links = self._document["links"]
        endpoints = [source_id, target_id]
        ports = [output_port, input_port]
        existing = next((link for link in links if link[:2] == endpoints), None)
        if existing is not None:
            if existing[2:] == ports:
                return
            self._remember_edit()
            existing[2:] = ports
        else:
            try:
                validate_connection(self._document, source_id, target_id, self._parallel_scheduler() is not None)
            except ValueError as error:
                self._show_error(error)
                return
            self._remember_edit()
            links.append(endpoints + ports)
        self._dirty = True
        self._populate_steps(target)
        self._schedule_autosave()
        self._update_state()

    def _reorder_step(self, source, target):
        if self._document is None:
            return
        steps = self._document["steps"]
        if source != target and 0 <= source < len(steps) and 0 <= target < len(steps):
            self._remember_edit()
            steps.insert(target, steps.pop(source))
            self._dirty = True
            self._populate_steps(target)
            self._schedule_autosave()
            self._update_state()

    def _insert_module(self, module, _index):
        if module in STEP_LABELS:
            point = self.flow.drop_position if self._parallel_scheduler() is not None else None
            position = [point.x(), point.y()] if point is not None else None
            if self._document is None:
                self._create_task_from_drop(module, position)
            else:
                self._add_step(step_type=module, position=position)

    def _create_task_from_drop(self, module, position):
        issue = self._refresh_node_environment().get(module)
        if issue:
            self._show_error(ValueError(issue))
            return
        empty = {"version": 3, "steps": [], "links": [], "start_position": [20, 20]}
        document = deepcopy(empty)
        step = self._new_step(module, position if position is not None else [20, 180])
        self.parameters.display_step(step)
        try:
            step["properties"].update(self.parameters.values())
            append_node(document, step, START, "bottom")
            base = str(tr("未命名"))
            existing = {name.casefold() for name in self.store.list_names()}
            number = 1
            while True:
                name = base if number == 1 else f"{base} {number}"
                if name.casefold() not in existing:
                    try:
                        self.store.create(name, document)
                        break
                    except FileExistsError:
                        pass
                number += 1
            self._refresh_directory()
            self._load_task(name, selected=0)
            self._edit_history.remember(empty)
            self._edit_step()
        except (OSError, ValueError) as error:
            self.parameters.display_step(None)
            self._show_error(error)

    def _parameters_changed(self, properties):
        item = self.steps.currentItem()
        if self._document is None or item is None:
            return
        index = item.data(0, Qt.ItemDataRole.UserRole)
        self._remember_edit(("parameters", index))
        step = self._document["steps"][index]
        if step["type"] in EXECUTION_LABELS:
            step["type"] = effective_kind(step["type"], properties)
        saved = step.setdefault("properties", {})
        saved.update(properties)
        if step["type"] in EXECUTION_LABELS and "SCRIPT_CONTENT" in properties:
            saved.pop("SCRIPT_PATH", None)
            saved.pop("SCRIPT_SOURCE", None)
        self._step_updated(index, item, step)

    def _node_name_changed(self, name):
        item = self.steps.currentItem()
        if self._document is None or item is None:
            return
        index = item.data(0, Qt.ItemDataRole.UserRole)
        step = self._document["steps"][index]
        name = name.strip()
        if name == step.get("name", ""):
            return
        self._remember_edit(("node_name", index))
        if name:
            step["name"] = name
        else:
            step.pop("name", None)
        self._step_updated(index, item, step)

    def _step_updated(self, index, item, step):
        item.setText(0, tr("{0}. {1}", index + 1, node_display_name(step)))
        self._dirty = True
        self.flow.clear_states()
        self.flow.update_step_text(index, step)
        self._refresh_parameter_preview(self._document["steps"], index)
        self._schedule_autosave()
        self._update_state()

    def _remember_edit(self, key=None):
        self._edit_history.remember(self._document, key)
        self.undo_notice.setVisible(self._edit_history.limited)
        self.flow.set_validation_issues([])

    def _restore_edit(self, redo=False):
        if self._document is None:
            return
        document = self._edit_history.restore(self._document, redo)
        self.undo_notice.setVisible(self._edit_history.limited)
        if document is not None:
            self._document = document
            self._dirty = document != self._saved_document
            self._artifacts = {}
            self.flow.set_validation_issues([])
            self._populate_steps()
            self._schedule_autosave()
            self._update_state()

    def _copy_step(self, index=None):
        if self._document is None:
            return
        if index is None:
            item = self.steps.currentItem()
            if item is None:
                return
            index = item.data(0, Qt.ItemDataRole.UserRole)
        step = deepcopy(self._document["steps"][index])
        step["position"] = self.flow.next_module_position(index, "right")
        for key in ("connection_disabled", "input_port", "output_port"):
            step.pop(key, None)
        if step["type"] == "MAVEN_BUILD":
            names = {entry.get("properties", {}).get("ARTIFACT_NAME", "artifact") for entry in self._document["steps"] if entry["type"] == "MAVEN_BUILD"}
            base = step["properties"].get("ARTIFACT_NAME", "artifact")
            suffix = 2
            while base + "_" + str(suffix) in names:
                suffix += 1
            step["properties"]["ARTIFACT_NAME"] = base + "_" + str(suffix)
        destination = len(self._document["steps"])
        try:
            self._insert_connected_node(step, index, "right")
        except ValueError as error:
            self._show_error(error)
            return
        self._dirty = True
        self._populate_steps(destination)
        if not self._autosave():
            self._update_state()

    def _arrange_steps(self):
        if self._document is None:
            return
        self._remember_edit()
        order, parents, _issues = execution_plan(self._document, check_connections=False, parallel=True)
        levels, layers = {}, {}
        for index in order:
            level = levels[index] = 1 + max((levels[parent] for parent in parents[index]), default=0)
            layers.setdefault(level, []).append(index)
        self._document["start_position"] = [40, 40]
        for level, indexes in layers.items():
            for column, index in enumerate(indexes):
                x = 40 + (column - (len(indexes) - 1) / 2) * 380
                self._document["steps"][index]["position"] = [x, 40 + level * 160]
        for link in self._document["links"]:
            link[2:] = ["", ""]
        self._dirty = True
        self._populate_steps()
        self._schedule_autosave()
        self._update_state()

    def _disconnect_step(self, endpoints):
        if self._document is None:
            return
        links = self._document["links"]
        link = next((link for link in links if tuple(link[:2]) == tuple(endpoints)), None)
        if link is not None:
            self._remember_edit()
            links.remove(link)
            self._dirty = True
            self._populate_steps()
            self._schedule_autosave()
            self._update_state()

    def _validate_flow(self, show_success=True, *, indexes=None, start_at=None, check_connections=True):
        if self._document is None:
            return False
        try:
            order, predecessors, issues = execution_plan(
                self._document, indexes=indexes, start_at=start_at, check_connections=check_connections,
                parallel=self._parallel_scheduler() is not None,
            )
            if not issues:
                _steps, issues = prepare_workflow(
                    self._document, self.execution_services.store, indexes=order, check_connections=False,
                    predecessors=predecessors if check_connections else None,
                    allow_existing_jars=indexes is not None or start_at is not None,
                )
        except (OSError, ValueError) as error:
            self._show_error(error)
            return False
        self.flow.set_validation_issues(issues)
        if not issues:
            if show_success:
                QMessageBox.information(self, tr("校验流程"), tr("流程校验通过"))
            return order
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("流程校验未通过"))
        dialog.setMinimumWidth(480)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(14)

        def locate(index):
            self.parameter_button.setChecked(True)
            self._select_flow_step(index)
            self.flow.select_step(index)
            dialog.accept()

        cards = QFrame()
        cards_layout = QVBoxLayout(cards)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(8)
        first_edit = None
        for index, message in issues:
            label = tr("任务")
            if index >= 0:
                label = tr("第 {0} 步：{1}", index + 1, node_display_name(self._document["steps"][index]))
            card = QFrame()
            card.setObjectName("taskPanel")
            row = QHBoxLayout(card)
            row.setContentsMargins(12, 10, 12, 10)
            row.setSpacing(12)
            details = QVBoxLayout()
            details.setSpacing(4)
            title = QLabel(label)
            title.setTextFormat(Qt.TextFormat.PlainText)
            title.setWordWrap(True)
            font = title.font()
            font.setBold(True)
            title.setFont(font)
            details.addWidget(title)
            problem = QLabel(message)
            problem.setTextFormat(Qt.TextFormat.PlainText)
            problem.setWordWrap(True)
            details.addWidget(problem)
            row.addLayout(details, 1)
            if index >= 0:
                edit = QPushButton(tr("编辑参数"))
                edit.setAutoDefault(False)
                edit.clicked.connect(lambda _checked=False, step=index: locate(step))
                row.addWidget(edit, alignment=Qt.AlignmentFlag.AlignVCenter)
                if first_edit is None:
                    first_edit = edit
            cards_layout.addWidget(card)

        if len(issues) > 3:
            scroll = QScrollArea()
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidgetResizable(True)
            scroll.setWidget(cards)
            scroll.setMinimumHeight(260)
            cards_layout.addStretch()
            layout.addWidget(scroll, 1)
        else:
            layout.addWidget(cards)
        footer = QHBoxLayout()
        footer.addStretch()
        close = QPushButton(tr("关闭"))
        close.setMinimumWidth(76)
        close.setAutoDefault(False)
        close.clicked.connect(dialog.accept)
        footer.addWidget(close)
        layout.addLayout(footer)
        (first_edit or close).setFocus()
        dialog.exec()
        dialog.deleteLater()
        return False


    def _history_write_failed(self, identifier, message):
        if identifier in self._history_failure_ids:
            return
        self._history_failure_ids.add(identifier)
        dialog = QMessageBox(self)
        dialog.setWindowTitle(tr("执行记录"))
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText(tr("执行记录保存失败：{0}", message))
        dialog.finished.connect(lambda _result: dialog.deleteLater())
        dialog.open()

    def _open_run_history(self):
        if self.current_name is None:
            return
        roots = [self._history_store.directory / "logs"]
        service = self.registry.get_service("log")
        if service is not None:
            roots.append(service.store.directory)
        try:
            run_id = self._selected_runs.get(self.current_name)
            dialog = RunHistoryDialog(
                self._history_store, STEP_LABELS, roots, run_id, self,
                pending=self._history_writer.snapshot(),
                active_ids=[identifier for identifier, run in self._runs.items() if run.active],
                task_name=self.current_name,
            )
            dialog.exec()
            dialog.deleteLater()
        except (OSError, ValueError) as error:
            self._show_error(error)


    def _run_label(self, run):
        state = "正在停止，请等待执行结束" if run.active and run.runner.stop.is_set() else STATES[run.record["state"]]
        return tr("执行 #{0} · {1} · {2}", run.number, run.task_name, tr(state))

    def _refresh_artifacts(self):
        identifier = self._selected_runs.get(self.current_name)
        run = self._runs.get(identifier)
        self._artifacts = run.artifacts if run is not None else {}
        self.parameters.upload.artifact_results = self._artifacts
        self.parameters.upload.refresh_jars()

    def _choose_run_to_stop(self):
        running = [run for run in self._runs.values() if run.active and not run.runner.stop.is_set()]
        if len(running) == 1:
            self.run_manager.stop(running[0])
        elif running:
            labels = [str(self._run_label(run)) for run in running]
            label, accepted = QInputDialog.getItem(self.window(), tr("停止任务"), tr("选择要停止的执行批次"), labels, editable=False)
            if accepted:
                self.run_manager.stop(running[labels.index(label)])

    def can_leave(self) -> bool:
        if not self._dirty or self.save_task(show_message=False):
            return True
        answer = QMessageBox.question(
            self, tr("存在未保存内容"), tr("是否先保存当前文件？"),
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save_task(show_message=False)
        if answer == QMessageBox.StandardButton.Discard:
            try:
                self._load_task(self.current_name)
            except (OSError, ValueError) as exc:
                self._show_error(exc)
                return False
            return True
        return False

    def can_close(self) -> bool:
        return self.can_leave()

    def _execute_from_step(self, index):
        self.execute_task(start_at=index)

    def _execute_selected_steps(self, indexes):
        self.execute_task(indexes, check_connections=False)

    def _execute_named_task(
        self, name: str, *, preview=None, source=None, indexes=None, start_at=None, legacy=False,
    ) -> None:
        if not self.select_item(name):
            return
        if source is not None and (indexes is not None or start_at is not None):
            visible = source["steps"]
            current = self._document["steps"]
            positions = {step["node_id"]: index for index, step in enumerate(current)}
            selected = (start_at,) if start_at is not None else indexes
            if all(visible[index]["node_id"] in positions for index in selected):
                selected = tuple(positions[visible[index]["node_id"]] for index in selected)
            elif not legacy or [
                {key: value for key, value in step.items() if key != "node_id"} for step in visible
            ] != [
                {key: value for key, value in step.items() if key != "node_id"} for step in current
            ]:
                self._show_error(ValueError(tr("流程节点已变化，请重新打开执行页面")))
                return
            if start_at is not None:
                start_at = selected[0]
            else:
                indexes = selected
        self.execute_task(indexes, start_at=start_at, check_connections=indexes is None, preview=preview)

    def execute_task(self, indexes=None, *, start_at=None, check_connections=True, preview=None):
        if not self.is_action_enabled("execute"):
            return
        current_page = preview.run_page if preview is not None else self._editor_run_page
        if current_page is not None and current_page.run.active:
            if preview is None and current_page.run.task_name == self.current_name:
                self._page_stack.setCurrentWidget(current_page)
            else:
                QMessageBox.information(self, tr("任务"), tr("任务正在执行，请等待完成"))
            return
        run_indexes = self._validate_flow(
            show_success=False, indexes=indexes, start_at=start_at, check_connections=check_connections,
        )
        if not run_indexes or not self.save_task(show_message=False):
            return
        try:
            run = self.run_manager.start(
                self.current_name, self._document, run_indexes, indexes=indexes, start_at=start_at,
                check_connections=check_connections, scheduler=self._parallel_scheduler(), artifacts=self._artifacts,
            )
        except (OSError, ValueError, RuntimeError) as error:
            self._show_error(error)
            return
        self._show_run_in_page(run, preview)

    def _show_run_in_page(self, run, preview):
        page = TaskRunPage(
            self.run_manager, run,
            execute=lambda **options: self._execute_named_task(
                preview.workspace_item_id if preview is not None else run.task_name,
                preview=preview, source=run.document, **options,
            ),
            back=(lambda: self._page_stack.setCurrentWidget(self._editor_view)) if preview is None else None,
        )
        appearance = self.registry.get_service("window_appearance")
        if appearance is not None:
            appearance.decorate_task(page)
        if preview is not None:
            preview.show_run(page)
        else:
            if self._editor_run_page is not None:
                self._page_stack.removeWidget(self._editor_run_page)
                self._editor_run_page.deleteLater()
            self._editor_run_page = page
            self._page_stack.addWidget(page)
            self._page_stack.setCurrentWidget(page)
        self._selected_runs[run.task_name] = run.record["id"]
        self._update_state()

    def _run_changed(self, run):
        if run.task_name == self.current_name and self._selected_runs.get(self.current_name) == run.record["id"]:
            if self._artifacts is not run.artifacts:
                self._refresh_artifacts()
        self.actions_changed.emit()

    def _show_error(self, error: Exception) -> None:
        if isinstance(error, WorkflowUpgradeRequired):
            prompt_activation(self.registry, self, tr("高级流程"), detail=error_message(error))
        else:
            QMessageBox.critical(self, tr("操作失败"), error_message(error))
