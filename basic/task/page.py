"""Basic task page integrated with the shared application shell."""

from copy import deepcopy
from time import time
from uuid import uuid4

from PySide6.QtCore import QEvent, QSignalBlocker, Qt
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QInputDialog, QMenu, QMessageBox, QPlainTextEdit, QSplitter, QVBoxLayout

from basic.log.viewer import LogViewer
from common.i18n import tr
from common.i18n.errors import error_message
from common.licensing.prompt import prompt_activation
from common.i18n.widgets import QAction, QDialog, QLabel, QPushButton, QTabWidget, QTreeWidget, QTreeWidgetItem
from common.qt.module_page import ModulePage
from common.settings.store import SettingsStore

from .edit_history import EditHistory
from .history import RunHistoryDialog, RunHistoryStore, RunHistoryWriter
from .validation import prepare_workflow
from .graph import (
    PARALLEL_REQUIRED, START, WorkflowUpgradeRequired, append_node, ensure_graph,
    execution_plan, graph_structure, remove_node, validate_connection,
)
from .store import TASK_SUFFIX, TaskStore
from .git.dialog import GitMergeDialog
from .runner import STEP_LABELS, TaskRunner
from .views import ModuleLibrary, TaskFlowView, parameter_summary
from .parameters import TaskParameterEditor
from .schema import CATEGORIES
from .execution.schema import STEP_LABELS as EXECUTION_LABELS, effective_kind
from .execution.connections import ExecutionServices
from .execution.editor import ExecutionStepDialog
from .shell_panel import ShellPanelBridge, ShellPanelDialog
from .health import HealthDialog
from .wait import WaitDialog
from .upload import STEP_LABELS as UPLOAD_LABELS, UploadDialog


class TaskPage(ModulePage):
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
        self._running = False
        self._output_task_name = None
        self._log_writer = None
        self._edit_history = EditHistory()
        self._saved_document = None
        self._history_store = RunHistoryStore(store.directory.parent / "task_history")
        self._history_writer = RunHistoryWriter(self._history_store, self)
        self._history_writer.failed.connect(self._history_write_failed)
        QApplication.instance().aboutToQuit.connect(self._history_writer.close)
        self.destroyed.connect(lambda *_args, writer=self._history_writer: writer.close())
        self._history_record = None
        self._history_error = None
        self._history_failure_ids = set()
        self._views_ready = False
        self.execution_services = ExecutionServices(store.directory.parent, self)
        self.execution_services.trust_requested.connect(self._confirm_task_host)
        self._runner = TaskRunner(self, self.execution_services)
        self._runner.message.connect(self._log)
        self._runner.finished.connect(self._finished)
        self._runner.step_state.connect(self._step_state)
        self._runner.conflict_requested.connect(self._show_conflicts)
        self._artifacts = {}
        self._runner.artifacts_ready.connect(self._artifacts_changed)
        self._runner.shell_requested.connect(self._open_shell_panel)
        self._shell_bridge = None
        self._conflict_dialog = None
        self.file_actions = {
            "new": self.create_task, "rename": self.rename_task,
            "copy": self.copy_task, "delete": self.delete_task, "save": self.save_task,
            "execute": self.execute_task,
        }
        self.setObjectName("taskEditor")
        self.setStyleSheet("QFrame#taskPanel { border: 1px solid palette(mid); border-radius: 8px; background: palette(base); } QLabel#panelHeading { padding: 6px 2px 10px 2px; font-weight: 600; } QLabel#taskHeading { font-size: 18px; font-weight: 600; } QFrame#taskToolBar QPushButton, QFrame#taskEditBar QPushButton { background: transparent; border: 1px solid transparent; padding: 3px 10px; min-height: 24px; } QFrame#taskToolBar QPushButton:hover:enabled, QFrame#taskEditBar QPushButton:hover:enabled { background: palette(alternate-base); border-color: palette(mid); } QFrame#taskToolBar QPushButton:checked, QFrame#taskToolBar QPushButton:checked:hover:enabled { background: palette(highlight); color: palette(highlighted-text); } QSplitter::handle { background: transparent; } QSplitter::handle:hover { background: palette(midlight); }")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        header = QHBoxLayout()
        self.title = QLabel(tr("任务"))
        self.title.setObjectName("taskHeading")
        header.addWidget(self.title)
        header.addStretch()
        self.notice = QLabel(tr("暂无任务"))
        header.addWidget(self.notice)
        layout.addLayout(header)
        bar_widget = QFrame()
        bar_widget.setObjectName("taskToolBar")
        bar = QHBoxLayout(bar_widget)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(4)
        self.add_step = QPushButton(tr("添加流程"))
        menu = QMenu(self.add_step)
        for category, kinds in CATEGORIES.items():
            category_menu = menu.addMenu(str(tr(category)))
            for step_type in kinds:
                action = QAction(tr(STEP_LABELS[step_type]), category_menu)
                action.triggered.connect(lambda _checked=False, kind=step_type: self._edit_step(adding=True, step_type=kind))
                category_menu.addAction(action)
        self.add_step.setMenu(menu)
        bar.addWidget(self.add_step)
        self.step_buttons = []
        for label, action in (("修改", self._edit_step), ("删除", self._remove_step)):
            button = QPushButton(tr(label))
            button.clicked.connect(lambda _checked=False, handler=action: handler())
            bar.addWidget(button)
            self.step_buttons.append(button)
        self.resolve_button = QPushButton(tr("解决冲突"))
        self.resolve_button.clicked.connect(self._reopen_conflicts)
        self.resolve_button.hide()
        bar.addWidget(self.resolve_button)
        self.stop_button = QPushButton(tr("停止"))
        self.stop_button.clicked.connect(self._stop_workflow)
        self.stop_button.hide()
        bar.addWidget(self.stop_button)
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
        tools_widget = QFrame()
        tools_widget.setObjectName("taskEditBar")
        tools = QHBoxLayout(tools_widget)
        tools.setContentsMargins(0, 0, 0, 0)
        tools.setSpacing(4)
        self.edit_actions = {}
        for text, callback in (("撤销", lambda: self._restore_edit()), ("重做", lambda: self._restore_edit(True)), ("复制节点", self._copy_step), ("自动排列", self._arrange_steps), ("校验流程", self._validate_flow), ("执行记录", self._open_run_history)):
            button = QPushButton(tr(text))
            button.clicked.connect(lambda _checked=False, handler=callback: handler())
            tools.addWidget(button)
            self.edit_actions[text] = button
        self.output_button = QPushButton(tr("执行输出"))
        self.output_button.setCheckable(True)
        tools.addWidget(self.output_button)
        tools.addStretch()
        layout.addWidget(tools_widget)
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
        self.flow.setToolTip(
            tr("拖动节点自由摆放；从任一方向的圆点拖向另一节点连接下一步；Ctrl＋滚轮缩放；拖动空白处移动画布")
            + "\n" + tr("按住 Ctrl 单击可多选节点") + "\n" + tr("点击四向箭头添加并连接节点")
        )
        self.parameters = TaskParameterEditor(services=self.execution_services)
        self.parameters.changed.connect(self._parameters_changed)
        self.library = ModuleLibrary()
        self.library_panel = self._view_panel(tr("模块库"), self.library)
        self.library_panel.setVisible(self._library_visible)
        self.flow_panel = self._view_panel(tr("流程视图"), self.flow)
        self.parameter_preview = QPlainTextEdit()
        self.parameter_preview.setReadOnly(True)
        self.parameter_tabs = QTabWidget()
        self.parameter_tabs.addTab(self.parameters, tr("编辑参数"))
        self.parameter_tabs.addTab(self.parameter_preview, tr("流程参数"))
        self.parameter_panel = QFrame()
        self.parameter_panel.setObjectName("taskPanel")
        self.parameter_panel.setFrameShape(QFrame.Shape.StyledPanel)
        inspector_layout = QVBoxLayout(self.parameter_panel)
        inspector_layout.setContentsMargins(8, 6, 8, 8)
        self.inspector_title = QLabel(tr("任务"))
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
        self.editor_splitter.setHandleWidth(6)
        self.editor_splitter.addWidget(self.library_panel)
        self.editor_splitter.addWidget(self.flow_panel)
        self.editor_splitter.addWidget(self.parameter_panel)
        self.editor_splitter.setStretchFactor(0, 0)
        self.editor_splitter.setStretchFactor(1, 2)
        self.editor_splitter.setStretchFactor(2, 1)
        self.editor_splitter.setSizes([220, 760, 340])
        layout.addWidget(self.editor_splitter, 2)
        self.output_view = LogViewer(self)
        self.output = self.output_view.text
        self.output.setMaximumBlockCount(3000)
        self.output_button.toggled.connect(self.output_view.setVisible)
        layout.addWidget(self.output_view, 1)
        self._views_ready = True
        self._update_state()

    def bind_registry(self, registry):
        super().bind_registry(registry)
        self.execution_services.log_service = registry.get_service("log")

    def _confirm_task_host(self, request):
        try:
            request["accepted"] = QMessageBox.question(self, tr("确认服务器主机密钥"), tr("服务器：{0}\n密钥类型：{1}\n指纹：{2}\n是否信任并保存？", request["host"], request["kind"], request["fingerprint"]), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
        finally:
            request["event"].set()

    def activate(self) -> None:
        try:
            self._refresh_directory()
            if self.current_name not in self._names:
                self.current_name = None
                self._document = None
                self._dirty = False
                self._populate_steps()
                if self._names:
                    self._load_task(self._names[0])
            self._update_state()
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
            self._load_task(item_id)
        except (OSError, ValueError) as exc:
            self._show_error(exc)
            return False
        return True

    def is_action_enabled(self, action_id: str) -> bool:
        if self._running:
            return False
        if action_id == "execute":
            return self._document is not None and bool(self._document["steps"])
        return action_id == "new" or (self.current_name is not None and action_id in self.file_actions)

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
        if QMessageBox.question(
            self, tr("删除"), tr("确定删除任务“{0}”吗？", self.current_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes:
            self._change("delete", self.current_name)

    def save_task(self, show_message: bool = True) -> bool:
        if self._running or self.current_name is None or self._document is None:
            return False
        try:
            self.store.save(self.current_name, self._document)
        except (OSError, ValueError) as exc:
            self._show_error(exc)
            return False
        self._dirty = False
        self._saved_document = deepcopy(self._document)
        self._update_state()
        self.status_changed.emit(tr("已保存：{0}", self.current_name))
        if show_message:
            QMessageBox.information(self, tr("保存"), tr("已保存：{0}", self.current_name))
        return True

    def _change(self, operation: str, *names: str) -> None:
        try:
            getattr(self.store, operation)(*names)
            if operation == "delete":
                if self.current_name == self._output_task_name:
                    self._output_task_name = None
                    self.output.clear()
                self.current_name = None
                self._document = None
                self._dirty = False
                self._populate_steps()
            elif operation == "rename" and names[0] == self._output_task_name:
                self._output_task_name = names[1]
            self._refresh_directory()
            selected = next(iter(self._names), None) if operation == "delete" else names[-1]
            if selected is not None:
                self._load_task(selected)
            else:
                self._update_state()
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

    def _load_task(self, name: str) -> None:
        document = self.store.load(name)
        ensure_graph(document)
        self._artifacts = {}
        self._edit_history.reset()
        self.undo_notice.hide()
        self.flow.set_validation_issues([])
        self._saved_document = deepcopy(document)
        self.current_name, self._document = name, document
        self._dirty = False
        self._populate_steps()
        self._update_state()
        self.flow.center_flow()

    def _refresh_directory(self) -> None:
        self._names = self.store.list_names()
        self.directory_changed.emit()

    def _update_state(self) -> None:
        has_output = self._output_task_name is not None and self.current_name == self._output_task_name
        self.output_button.setEnabled(has_output)
        if not has_output:
            self.output_button.setChecked(False)
        self.output_view.setVisible(has_output and self.output_button.isChecked())
        self.title.setText(self.current_name if self.current_name is not None else tr("任务"))
        self.notice.setText(tr("步骤数量：{0}", len(self._document["steps"])) if self._document is not None else tr("暂无任务"))
        editable = self._document is not None and not self._running
        self.add_step.setEnabled(editable)
        self.library.setEnabled(editable)
        self.flow.set_editable(editable)
        self.flow.parallel_enabled = editable and self._parallel_scheduler() is not None
        self.parameters.form_widget.setEnabled(editable)
        self.parameters.execution.setEnabled(editable)
        self.parameters.upload.setEnabled(editable)
        self.parameters.wait.setEnabled(editable)
        self.parameters.health.setEnabled(editable)
        self.parameters.shell_panel.setEnabled(editable)
        self.stop_button.setVisible(self._running)
        for text, button in self.edit_actions.items():
            button.setEnabled(editable or text == "执行记录")
        self.edit_actions["撤销"].setEnabled(editable and bool(self._edit_history.undo_stack))
        self.edit_actions["重做"].setEnabled(editable and bool(self._edit_history.redo_stack))
        self.edit_actions["复制节点"].setEnabled(editable and self.steps.currentItem() is not None)
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
            label = STEP_LABELS.get(step["type"], step["type"])
            item = QTreeWidgetItem([tr("{0}. {1}", index + 1, tr(label)), str(step.get("properties", {}).get("TARGET_BRANCH", ""))])
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
        if not self.flow_button.isChecked() and not self.parameter_button.isChecked():
            button = self.sender()
            blocker = QSignalBlocker(button)
            button.setChecked(True)
            del blocker
        self.flow_panel.setVisible(self.flow_button.isChecked())
        self.parameter_panel.setVisible(self.parameter_button.isChecked())

    def _view_panel(self, title, view):
        panel = QFrame()
        panel.setObjectName("taskPanel")
        panel.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(6)
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
        self.parameters.display_step(entries[index] if index is not None and 0 <= index < len(entries) else None, not self._running)
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
        self.parameters.display_step(entries[index] if index is not None and 0 <= index < len(entries) else None, not self._running)
        self._refresh_parameter_preview(entries, index)

    def _refresh_parameter_preview(self, entries, index):
        selected = index is not None and 0 <= index < len(entries)
        if selected:
            step = entries[index]
            label = STEP_LABELS.get(step["type"], step["type"])
            self.inspector_title.setText(tr("{0}. {1}", index + 1, tr(label)))
        else:
            self.inspector_title.setText(self.current_name or tr("任务"))
            self.task_overview.setText(tr("步骤数量：{0}", len(entries)) if self._document is not None else tr("暂无任务"))
        data = parameter_summary(entries, index if selected else None)
        if self.parameter_preview.toPlainText() != data:
            self.parameter_preview.setPlainText(data)
        self.parameter_tabs.setTabVisible(0, selected)
        self.parameter_tabs.setTabVisible(1, not selected)
        self.parameter_tabs.setCurrentWidget(self.parameters if selected else self.parameter_preview)
        self.parameter_tabs.setVisible(bool(entries))
        self.task_overview.setVisible(not selected)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in {QEvent.Type.LanguageChange, QEvent.Type.PaletteChange} and getattr(self, "_views_ready", False):
            self._refresh_views()

    def _update_step_actions(self):
        item = self.steps.currentItem()
        index = self.steps.indexOfTopLevelItem(item) if item is not None else -1
        enabled = not self._running and index >= 0
        self.edit_actions["复制节点"].setEnabled(enabled)
        for button in self.step_buttons:
            button.setEnabled(enabled)
        if enabled:
            self.step_buttons[0].setEnabled(self._document["steps"][index]["type"] in STEP_LABELS)

    def _preceding_artifacts(self, index, *, include_node=False):
        if self._document is None or index is None or index < 0:
            return []
        ids, _outgoing, incoming = graph_structure(self._document)
        node = ids[index]
        found = set()
        pending = [node] if include_node else list(incoming[node])
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

    def _check_node_limit(self):
        limit = 5
        if len(self._document["steps"]) >= limit and self._parallel_scheduler() is None:
            raise WorkflowUpgradeRequired(tr("免费版每个流程最多添加 {0} 个节点，增加更多节点需要付费授权", limit))

    def _insert_connected_node(self, step, source_index, direction, replace_link=None):
        self._check_node_limit()
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
        self._edit_step(adding=True, source_index=index, direction=direction, step_type=kind)

    def _insert_on_edge(self, endpoints, kind):
        if self._running or self._document is None:
            return
        link = next((link for link in self._document["links"] if tuple(link[:2]) == endpoints), None)
        if link is None:
            return
        source_index = -1 if link[0] == START else next(index for index, step in enumerate(self._document["steps"]) if step["node_id"] == link[0])
        direction = self.flow.edge_output_port(endpoints)
        position = self.flow.insertion_position(endpoints, source_index, direction)
        self._edit_step(adding=True, source_index=source_index, direction=direction, step_type=kind, position=position, replace_link=list(link))

    def _artifacts_changed(self, artifacts):
        self._artifacts = artifacts
        self.parameters.upload.artifact_results = artifacts
        self.parameters.upload.refresh_jars()

    def _edit_step(self, *, adding=False, source_index=None, direction="bottom", step_type="MERGE_BRANCH", position=None, replace_link=None):
        if self._running or self._document is None:
            return
        item = self.steps.currentItem()
        if not adding and item is None:
            return
        if adding:
            try:
                self._check_node_limit()
            except ValueError as error:
                self._show_error(error)
                return
            if source_index is None:
                source_index = self._default_add_source()
        index = len(self._document["steps"]) if adding else item.data(0, Qt.ItemDataRole.UserRole)
        if not adding:
            step_type = self._document["steps"][index]["type"]
        if step_type not in STEP_LABELS:
            return
        properties = None if adding else self._document["steps"][index].get("properties", {})
        dialog = ExecutionStepDialog(self.execution_services, step_type, properties, self) if step_type in EXECUTION_LABELS else UploadDialog(self.execution_services, step_type, properties, self, artifact_options=self._preceding_artifacts(source_index if adding else index, include_node=adding), artifact_results=self._artifacts) if step_type in UPLOAD_LABELS else WaitDialog(properties, self) if step_type == "WAIT" else HealthDialog(self.execution_services, properties, self) if step_type == "HEALTH_CHECK" else ShellPanelDialog(self.execution_services, properties, self) if step_type == "OPEN_SHELL" else GitMergeDialog(properties, self, step_type)
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                values = dialog.properties()
                if step_type in EXECUTION_LABELS:
                    step_type = effective_kind(step_type, values)
                if adding:
                    step = {"type": step_type, "properties": values}
                    step["position"] = position if position is not None else self.flow.next_module_position(source_index, direction)
                    try:
                        self._insert_connected_node(step, source_index, direction, replace_link)
                    except ValueError as error:
                        self._show_error(error)
                        return
                else:
                    self._remember_edit()
                    self._document["steps"][index]["type"] = step_type
                    saved = self._document["steps"][index].setdefault("properties", {})
                    saved.update(values)
                    if step_type in EXECUTION_LABELS and "SCRIPT_CONTENT" in values:
                        saved.pop("SCRIPT_PATH", None)
                        saved.pop("SCRIPT_SOURCE", None)
                self._dirty = True
                self._populate_steps(index)
                self._update_state()
        finally:
            dialog.deleteLater()

    def _remove_step(self, index=None):
        if self._running or self._document is None:
            return
        if index is None:
            item = self.steps.currentItem()
            if item is None:
                return
            index = item.data(0, Qt.ItemDataRole.UserRole)
        self._remove_steps((index,))

    def _remove_steps(self, indexes):
        if self._running or self._document is None:
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
        self._update_state()

    def _position_step(self, index, position):
        if self._running or self._document is None:
            return
        if -1 <= index < len(self._document["steps"]):
            self._remember_edit()
            if index == -1:
                self._document["start_position"] = position
            else:
                self._document["steps"][index]["position"] = position
            self._dirty = True
            self._update_state()

    def _can_connect_steps(self, source, target):
        if self._running or self._document is None or source == target:
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
        if self._running or self._document is None or source == target:
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
        self._update_state()

    def _reorder_step(self, source, target):
        if self._running or self._document is None:
            return
        steps = self._document["steps"]
        if source != target and 0 <= source < len(steps) and 0 <= target < len(steps):
            self._remember_edit()
            steps.insert(target, steps.pop(source))
            self._dirty = True
            self._populate_steps(target)
            self._update_state()

    def _insert_module(self, module, _index):
        if module in STEP_LABELS:
            point = self.flow.drop_position if self._parallel_scheduler() is not None else None
            position = [point.x(), point.y()] if point is not None else None
            self._edit_step(adding=True, step_type=module, position=position)

    def _parameters_changed(self, properties):
        item = self.steps.currentItem()
        if self._running or self._document is None or item is None:
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
        self._dirty = True
        self.flow.clear_states()
        self.flow.display_steps(self._document["steps"], index, graph=self._document)
        self._refresh_parameter_preview(self._document["steps"], index)
        self._update_state()

    def _remember_edit(self, key=None):
        self._edit_history.remember(self._document, key)
        self.undo_notice.setVisible(self._edit_history.limited)
        self.flow.set_validation_issues([])

    def _restore_edit(self, redo=False):
        if self._running or self._document is None:
            return
        document = self._edit_history.restore(self._document, redo)
        self.undo_notice.setVisible(self._edit_history.limited)
        if document is not None:
            self._document = document
            self._dirty = document != self._saved_document
            self._artifacts = {}
            self.flow.set_validation_issues([])
            self._populate_steps()
            self._update_state()

    def _copy_step(self, index=None):
        if self._running or self._document is None:
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
        self._update_state()

    def _arrange_steps(self):
        if self._running or self._document is None:
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
        self._update_state()

    def _disconnect_step(self, endpoints):
        if self._running or self._document is None:
            return
        links = self._document["links"]
        link = next((link for link in links if tuple(link[:2]) == tuple(endpoints)), None)
        if link is not None:
            self._remember_edit()
            links.remove(link)
            self._dirty = True
            self._populate_steps()
            self._update_state()

    def _validate_flow(self, show_success=True, *, indexes=None, start_at=None, check_connections=True):
        if self._document is None or self._running:
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
        dialog.resize(760, 360)
        layout = QVBoxLayout(dialog)
        tree = QTreeWidget()
        tree.setRootIsDecorated(False)
        tree.setHeaderLabels([tr("流程"), tr("问题")])
        for index, message in issues:
            label = str(tr("第 {0} 步", index + 1)) if index >= 0 else str(tr("任务"))
            item = QTreeWidgetItem([label, message])
            item.setData(0, Qt.ItemDataRole.UserRole, index)
            tree.addTopLevelItem(item)
        def locate(item, _column):
            index = item.data(0, Qt.ItemDataRole.UserRole)
            if index >= 0:
                self._select_flow_step(index)
                self.flow.select_step(index)
                dialog.accept()
        tree.itemDoubleClicked.connect(locate)
        layout.addWidget(QLabel(tr("双击问题可定位到对应节点")))
        layout.addWidget(tree)
        close = QPushButton(tr("关闭"))
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()
        dialog.deleteLater()
        return False

    def _save_run_record(self):
        try:
            self._history_writer.submit(self._history_record)
        except (OSError, ValueError) as error:
            self._history_write_failed(self._history_record["id"], str(error))

    def _history_write_failed(self, identifier, message):
        self._history_error = ValueError(tr("执行记录保存失败：{0}", message))
        if identifier in self._history_failure_ids:
            return
        self._history_failure_ids.add(identifier)
        dialog = QMessageBox(self)
        dialog.setWindowTitle(tr("执行记录"))
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText(str(self._history_error))
        dialog.finished.connect(lambda _result: dialog.deleteLater())
        dialog.open()

    def _open_run_history(self):
        roots = [self._history_store.directory / "logs"]
        service = self.registry.get_service("log")
        if service is not None:
            roots.append(service.store.directory)
        try:
            dialog = RunHistoryDialog(self._history_store, STEP_LABELS, roots, self._history_record["id"] if self._history_record else None, self, pending=self._history_writer.snapshot())
            dialog.exec()
            dialog.deleteLater()
        except (OSError, ValueError) as error:
            self._show_error(error)

    def _open_shell_panel(self, request):
        if self._shell_bridge is None:
            self._shell_bridge = ShellPanelBridge(self.registry, self)
        self._shell_bridge.open(request)

    def _stop_workflow(self):
        self._runner.stop.set()
        if self._conflict_dialog is not None:
            dialog = self._conflict_dialog
            dialog.reject()
            dialog.done(QDialog.DialogCode.Rejected)

    def _show_conflicts(self, request):
        if self._runner.stop.is_set():
            request["event"].set()
            return
        from .git.conflict_dialog import ConflictDialog
        try:
            dialog = ConflictDialog(request, self)
            dialog.setWindowTitle(tr("解决冲突：{0}", self.current_name))
            self._conflict_dialog = dialog
            dialog.finished.connect(lambda result: self._conflicts_finished(request, dialog, result))
            self.resolve_button.show()
            dialog.show()
        except Exception as exc:
            request["event"].set()
            self._show_error(exc)

    def _conflicts_finished(self, request, dialog, result):
        request["answer"] = dict(dialog.resolutions) if result == QDialog.DialogCode.Accepted else None
        self._conflict_dialog = None
        self.resolve_button.hide()
        request["event"].set()
        dialog.deleteLater()

    def _reopen_conflicts(self):
        if self._conflict_dialog is not None:
            self._conflict_dialog.show()
            self._conflict_dialog.raise_()
            self._conflict_dialog.activateWindow()

    def _step_state(self, index, state):
        if self._history_record is not None and index < len(self._history_record["steps"]):
            step = self._history_record["steps"][index]
            step["state"] = state
            if state == "running" and step["started"] is None:
                step["started"] = time()
            if state in {"success", "failed"}:
                step["finished"] = time()
            self._save_run_record()
        self.flow.set_step_state(index, state)

    def can_leave(self) -> bool:
        if self._running:
            QMessageBox.information(self, tr("任务"), tr("任务正在执行，请等待完成"))
            return False
        if not self._dirty:
            return True
        answer = QMessageBox.question(
            self, tr("存在未保存内容"), tr("是否先保存当前文件？"),
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save_task()
        if answer == QMessageBox.StandardButton.Discard:
            try:
                self._load_task(self.current_name)
            except (OSError, ValueError) as exc:
                self._show_error(exc)
                return False
            return True
        return False

    def _execute_from_step(self, index):
        self.execute_task(start_at=index)

    def _execute_selected_steps(self, indexes):
        self.execute_task(indexes, check_connections=False)

    def execute_task(self, indexes=None, *, start_at=None, check_connections=True):
        if not self.is_action_enabled("execute"):
            return
        run_indexes = self._validate_flow(
            show_success=False, indexes=indexes, start_at=start_at, check_connections=check_connections,
        )
        if not run_indexes:
            return
        if not self.save_task(show_message=False):
            return
        service = self.registry.get_service("log")
        if service is not None:
            try:
                self._log_writer = service.open_session("task", self.current_name)
            except (OSError, ValueError) as exc:
                self._show_error(exc)
                return
        try:
            if self._log_writer is None:
                from basic.log.writer import LogWriter
                self._log_writer = LogWriter(self._history_store.directory / "logs" / (uuid4().hex + ".log"))
            self._history_error = None
            self._history_failure_ids.clear()
            self._history_record = self._history_store.create(self.current_name, self._document["steps"], self._log_writer.path)
            self._history_writer.submit(self._history_record)
        except (OSError, ValueError) as error:
            if self._log_writer is not None:
                self._log_writer.close()
                self._log_writer = None
            self._show_error(error)
            return
        self.output.clear()
        self._output_task_name = self.current_name
        self.output_button.setChecked(True)
        self._running = True
        self.flow.clear_states(waiting_indexes=run_indexes)
        self._update_state()
        try:
            self._runner.start(
                deepcopy(self._document), indexes=indexes, start_at=start_at,
                check_connections=check_connections, scheduler=self._parallel_scheduler(),
                artifacts=self._artifacts,
            )
        except RuntimeError as exc:
            self._finished(False, tr("任务失败：{0}", error_message(exc)))

    def _log(self, message):
        self.output.appendPlainText(str(message))
        if self._log_writer is not None:
            self._log_writer.event("task", str(message))

    def _finished(self, success, message):
        self._running = False
        self._log(message)
        if self._history_record is not None:
            self._history_record["finished"] = time()
            self._history_record["state"] = "success" if success else "stopped" if self._runner.stop.is_set() else "failed"
            self._history_record["message"] = str(message)
            if self._runner.stop.is_set():
                for step in self._history_record["steps"]:
                    if step["state"] == "failed":
                        step["state"] = "stopped"
            self._save_run_record()
            self._history_record = None
        if self._log_writer is not None:
            self._log_writer.close()
            self._log_writer = None
        self.status_changed.emit(message)
        self._update_state()
        self.parameters.upload.refresh_jars()
        if not success:
            QMessageBox.warning(self, tr("任务"), message)

    def _show_error(self, error: Exception) -> None:
        if isinstance(error, WorkflowUpgradeRequired):
            prompt_activation(self.registry, self, tr("高级流程"), detail=error_message(error))
        else:
            QMessageBox.critical(self, tr("操作失败"), error_message(error))
