"""Basic task page integrated with the shared application shell."""

from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from time import time
from uuid import uuid4

from PySide6.QtCore import QEvent, QSignalBlocker, Qt
from PySide6.QtWidgets import QApplication, QComboBox, QFrame, QHBoxLayout, QInputDialog, QMenu, QMessageBox, QPlainTextEdit, QSplitter, QVBoxLayout

from basic.log.viewer import LogViewer
from basic.log.writer import LogWriter
from common.i18n import tr
from common.i18n.errors import error_message
from common.licensing.prompt import prompt_activation
from common.i18n.widgets import QAction, QDialog, QLabel, QPushButton, QTabWidget, QTreeWidget, QTreeWidgetItem
from common.qt.module_page import ModulePage
from common.settings.store import SettingsStore

from .edit_history import EditHistory
from .history import STATES, RunHistoryDialog, RunHistoryStore, RunHistoryWriter
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


@dataclass
class WorkflowRun:
    runner: TaskRunner
    record: dict
    writer: LogWriter
    task_name: str
    number: int
    node_ids: tuple[str, ...]
    states: dict[int, str]
    output: deque[str] = field(default_factory=lambda: deque(maxlen=3000))
    artifacts: dict = field(default_factory=dict)
    conflict_dialog: QDialog | None = None

    @property
    def active(self) -> bool:
        return self.record["finished"] is None


class TaskPage(ModulePage):
    uses_panel_workspace = True

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
        self._runs: dict[str, WorkflowRun] = {}
        self._selected_runs: dict[str, str] = {}
        self._displayed_run: WorkflowRun | None = None
        self._run_number = 0
        self._edit_history = EditHistory()
        self._saved_document = None
        self._history_store = RunHistoryStore(store.directory.parent / "task_history")
        self._history_writer = RunHistoryWriter(self._history_store, self)
        self._history_writer.failed.connect(self._history_write_failed)
        QApplication.instance().aboutToQuit.connect(self._history_writer.close)
        self.destroyed.connect(lambda *_args, writer=self._history_writer: writer.close())
        self._history_failure_ids = set()
        self._views_ready = False
        self.execution_services = ExecutionServices(store.directory.parent, self)
        self.execution_services.trust_requested.connect(self._confirm_task_host)
        self._artifacts = {}
        self._shell_bridge = None
        self.file_actions = {
            "new": self.create_task, "rename": self.rename_task,
            "copy": self.copy_task, "delete": self.delete_task, "save": self.save_task,
            "execute": self.execute_task, "stop": self._choose_run_to_stop,
        }
        self.setObjectName("taskEditor")
        self.setStyleSheet("QLabel#panelHeading { padding: 6px 2px 10px 2px; font-weight: 600; } QLabel#taskHeading { font-size: 18px; font-weight: 600; } QFrame#taskToolBar QPushButton { background: transparent; border: 1px solid transparent; padding: 3px 10px; min-height: 24px; } QFrame#taskToolBar QPushButton:hover:enabled { background: palette(alternate-base); border-color: palette(mid); } QSplitter::handle { background: transparent; } QSplitter::handle:hover { background: palette(midlight); }")
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
        bar_widget.setStyleSheet(
            "QFrame#taskToolBar QPushButton:checked, "
            "QFrame#taskToolBar QPushButton:checked:hover:enabled { "
            "background: palette(highlight); color: palette(highlighted-text); }"
        )
        bar_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
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
        self.resolve_button = QPushButton(tr("解决冲突"))
        self.resolve_button.clicked.connect(self._reopen_conflicts)
        self.resolve_button.hide()
        bar.addWidget(self.resolve_button)
        self.stop_button = QPushButton(tr("停止"))
        self.stop_button.clicked.connect(self._stop_selected_run)
        self.stop_button.hide()
        bar.addWidget(self.stop_button)
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
        self.output_action = QAction(tr("执行输出"), bar_widget)
        self.output_action.setCheckable(True)
        bar_widget.addAction(self.output_action)
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
        output_header = QHBoxLayout()
        output_header.addWidget(QLabel(tr("执行批次")))
        self.run_choices = QComboBox()
        self.run_choices.currentIndexChanged.connect(self._select_run)
        output_header.addWidget(self.run_choices, 1)
        output_panel = QVBoxLayout()
        output_panel.addLayout(output_header)
        self.output_view = LogViewer(self, output_header)
        self.output = self.output_view.text
        self.output.setMaximumBlockCount(3000)
        self.output_panel = QFrame()
        output_panel.addWidget(self.output_view, 1)
        self.output_panel.setLayout(output_panel)
        self.output_action.toggled.connect(self.output_panel.setVisible)
        layout.addWidget(self.output_panel, 1)
        self._views_ready = True
        self.new_panel_requested.connect(self.create_task)
        self._update_state()

    def bind_registry(self, registry):
        super().bind_registry(registry)
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
        if action_id == "stop":
            return any(run.active and not run.runner.stop.is_set() for run in self._runs.values())
        if action_id == "execute":
            return self._document is not None and bool(self._document["steps"])
        if self._running:
            return action_id in {"new", "copy"}
        return action_id == "new" or (self.current_name is not None and action_id in self.file_actions)

    @property
    def _running(self) -> bool:
        return any(run.active and run.task_name == self.current_name for run in self._runs.values())

    def create_task(self) -> None:
        if not self.can_leave():
            return
        name = self._ask_name(tr("新建"))
        if name is not None:
            self._change("create", name)

    def rename_task(self) -> None:
        if self._running or self.current_name is None or not self.can_leave():
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
        if self._running or self.current_name is None or not self.can_leave():
            return
        if QMessageBox.question(
            self, tr("删除"), tr("确定删除任务“{0}”吗？", self.current_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes:
            self._change("delete", self.current_name)

    def save_task(self, show_message: bool = True) -> bool:
        if self.current_name is None or self._document is None:
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
                self._selected_runs.pop(names[0], None)
                self._runs = {key: run for key, run in self._runs.items() if run.task_name != names[0]}
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
        self._refresh_run_choices()
        self.title.setText(self.current_name if self.current_name is not None else tr("任务"))
        self.setWindowTitle(self.title.text() + (" *" if self._dirty else ""))
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

    def _artifacts_changed(self, run, artifacts):
        run.artifacts = artifacts
        if run is self._displayed_run:
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

    def _save_run_record(self, run):
        try:
            self._history_writer.submit(run.record)
        except (OSError, ValueError) as error:
            self._history_write_failed(run.record["id"], str(error))

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
        roots = [self._history_store.directory / "logs"]
        service = self.registry.get_service("log")
        if service is not None:
            roots.append(service.store.directory)
        try:
            run_id = self.run_choices.currentData()
            dialog = RunHistoryDialog(self._history_store, STEP_LABELS, roots, run_id, self, pending=self._history_writer.snapshot())
            dialog.exec()
            dialog.deleteLater()
        except (OSError, ValueError) as error:
            self._show_error(error)

    def _open_shell_panel(self, request):
        if self._shell_bridge is None:
            self._shell_bridge = ShellPanelBridge(self.registry, self)
        self._shell_bridge.open(request)

    def _run_label(self, run):
        state = "正在停止，请等待执行结束" if run.active and run.runner.stop.is_set() else STATES[run.record["state"]]
        return tr("执行 #{0} · {1} · {2}", run.number, run.task_name, tr(state))

    def _refresh_run_choices(self):
        task_name = self.current_name
        preferred_id = self._selected_runs.get(task_name)
        with QSignalBlocker(self.run_choices):
            self.run_choices.clear()
            for identifier, run in reversed(self._runs.items()):
                if run.task_name == task_name:
                    self.run_choices.addItem(self._run_label(run), identifier)
            self.run_choices.setCurrentIndex(max(0, self.run_choices.findData(preferred_id)))
        self._select_run()
        has_output = self.run_choices.count() > 0
        self.output_action.setEnabled(has_output)
        self.output_panel.setVisible(has_output and self.output_action.isChecked())

    def _select_run(self, _index=-1):
        identifier = self.run_choices.currentData()
        run = self._runs.get(identifier)
        if run is not None:
            self._selected_runs[run.task_name] = identifier
        if run is not self._displayed_run:
            self._displayed_run = run
            self.output.setPlainText("\n".join(run.output) if run else "")
            self.output.verticalScrollBar().setValue(self.output.verticalScrollBar().maximum())
            if run is not None:
                self._artifacts_changed(run, run.artifacts)
            else:
                self._clear_artifacts()
            self._display_run_states()
        self.stop_button.setVisible(run is not None and run.active)
        self.stop_button.setEnabled(run is not None and run.active and not run.runner.stop.is_set())
        self.resolve_button.setVisible(run is not None and run.conflict_dialog is not None)

    def _clear_artifacts(self):
        self._artifacts = {}
        self.parameters.upload.artifact_results = self._artifacts
        self.parameters.upload.refresh_jars()

    def _display_run_states(self):
        self.flow.clear_states()
        run = self._displayed_run
        if run is None or self._document is None:
            return
        current = {step["node_id"]: index for index, step in enumerate(self._document["steps"])}
        for index, state in run.states.items():
            node_index = current.get(run.node_ids[index])
            if node_index is not None:
                self.flow.set_step_state(node_index, state)

    def _choose_run_to_stop(self):
        running = [run for run in self._runs.values() if run.active and not run.runner.stop.is_set()]
        if len(running) == 1:
            self._stop_workflow(running[0])
        elif running:
            labels = [str(self._run_label(run)) for run in running]
            label, accepted = QInputDialog.getItem(self.window(), tr("停止任务"), tr("选择要停止的执行批次"), labels, editable=False)
            if accepted:
                self._stop_workflow(running[labels.index(label)])

    def _stop_selected_run(self):
        self._stop_workflow(self._displayed_run)

    def _stop_workflow(self, run):
        if run is None or not run.active or run.runner.stop.is_set():
            return
        run.runner.stop.set()
        message = tr("正在停止，请等待执行结束")
        self._log(run, message)
        self.status_changed.emit(message)
        self._refresh_run_choices()
        self.actions_changed.emit()
        if run.conflict_dialog is not None:
            dialog = run.conflict_dialog
            dialog.reject()
            dialog.done(QDialog.DialogCode.Rejected)

    def _show_conflicts(self, run, request):
        if run.runner.stop.is_set():
            request["event"].set()
            return
        from .git.conflict_dialog import ConflictDialog
        try:
            dialog = ConflictDialog(request, self)
            dialog.setWindowTitle(tr("解决冲突：{0}", self._run_label(run)))
            run.conflict_dialog = dialog
            dialog.finished.connect(lambda result: self._conflicts_finished(run, request, dialog, result))
            self._select_run()
            dialog.show()
        except Exception as exc:
            request["event"].set()
            self._show_error(exc)

    def _conflicts_finished(self, run, request, dialog, result):
        request["answer"] = dict(dialog.resolutions) if result == QDialog.DialogCode.Accepted else None
        run.conflict_dialog = None
        self._select_run()
        request["event"].set()
        dialog.deleteLater()

    def _reopen_conflicts(self):
        dialog = self._displayed_run.conflict_dialog if self._displayed_run else None
        if dialog is not None:
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()

    def _step_state(self, run, index, state):
        if index < len(run.record["steps"]):
            step = run.record["steps"][index]
            step["state"] = state
            if state == "running" and step["started"] is None:
                step["started"] = time()
            if state in {"success", "failed"}:
                step["finished"] = time()
            self._save_run_record(run)
            run.states[index] = state
            if run is self._displayed_run:
                self._display_run_states()

    def can_leave(self) -> bool:
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

    def can_close(self) -> bool:
        if any(run.active for run in self._runs.values()):
            QMessageBox.information(self, tr("任务"), tr("任务正在执行，请等待完成"))
            return False
        return self.can_leave()

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
        if (self._dirty or not self._running) and not self.save_task(show_message=False):
            return
        document = deepcopy(self._document)
        task_name = self.current_name
        service = self.registry.get_service("log")
        writer = None
        try:
            writer = (
                service.open_session("task", task_name) if service is not None
                else LogWriter(self._history_store.directory / "logs" / (uuid4().hex + ".log"))
            )
            record = self._history_store.create(task_name, document["steps"], writer.path)
            self._history_writer.submit(record)
        except (OSError, ValueError) as error:
            if writer is not None:
                writer.close()
            self._show_error(error)
            return
        runner = TaskRunner(self, self.execution_services)
        self._run_number += 1
        run = WorkflowRun(
            runner, record, writer, task_name, self._run_number,
            tuple(step["node_id"] for step in document["steps"]),
            dict.fromkeys(run_indexes, "waiting"),
        )
        runner.message.connect(lambda message: self._log(run, message), Qt.ConnectionType.QueuedConnection)
        runner.finished.connect(lambda success, message: self._finished(run, success, message), Qt.ConnectionType.QueuedConnection)
        runner.step_state.connect(lambda index, state: self._step_state(run, index, state), Qt.ConnectionType.QueuedConnection)
        runner.conflict_requested.connect(lambda request: self._show_conflicts(run, request), Qt.ConnectionType.QueuedConnection)
        runner.artifacts_ready.connect(lambda artifacts: self._artifacts_changed(run, artifacts), Qt.ConnectionType.QueuedConnection)
        runner.shell_requested.connect(self._open_shell_panel)
        artifacts = self._artifacts
        self._runs[record["id"]] = run
        self._selected_runs[task_name] = record["id"]
        self.output_action.setChecked(True)
        try:
            runner.start(
                document, indexes=indexes, start_at=start_at,
                check_connections=check_connections, scheduler=self._parallel_scheduler(),
                artifacts=artifacts,
            )
        except RuntimeError as exc:
            self._finished(run, False, tr("任务失败：{0}", error_message(exc)))
        else:
            self._update_state()

    def _log(self, run, message):
        text = str(message)
        run.output.extend(text.split("\n"))
        if run is self._displayed_run:
            self.output.appendPlainText(text)
        run.writer.event("task", text)

    def _finished(self, run, success, message):
        self._log(run, message)
        stopped = not success and run.runner.stop.is_set()
        run.record["finished"] = time()
        run.record["state"] = "success" if success else "stopped" if stopped else "failed"
        run.record["message"] = str(message)
        if stopped:
            for index, step in enumerate(run.record["steps"]):
                if step["state"] == "failed":
                    step["state"] = "stopped"
                    run.states.pop(index, None)
        run.states = {index: state for index, state in run.states.items() if state in {"success", "failed"}}
        self._save_run_record(run)
        run.writer.close()
        run.runner.deleteLater()
        if run is self._displayed_run:
            self._display_run_states()
            self.parameters.upload.refresh_jars()
        result = tr("{0}：{1}", self._run_label(run), message)
        self.status_changed.emit(result)
        completed = [key for key, other in self._runs.items() if other.task_name == run.task_name and not other.active]
        selected_id = self._selected_runs.get(run.task_name)
        for key in completed[:-10]:
            if key != selected_id:
                del self._runs[key]
        self._update_state()
        if not success:
            dialog = QMessageBox(self.window())
            dialog.setIcon(QMessageBox.Icon.Warning)
            dialog.setWindowTitle(tr("任务"))
            dialog.setTextFormat(Qt.TextFormat.PlainText)
            dialog.setText(result)
            dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
            dialog.finished.connect(lambda _result: dialog.deleteLater())
            dialog.open()

    def _show_error(self, error: Exception) -> None:
        if isinstance(error, WorkflowUpgradeRequired):
            prompt_activation(self.registry, self, tr("高级流程"), detail=error_message(error))
        else:
            QMessageBox.critical(self, tr("操作失败"), error_message(error))
