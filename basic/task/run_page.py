"""Read-only view of one workflow execution snapshot."""
from time import monotonic, time
from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QMessageBox, QSplitter, QStackedLayout, QVBoxLayout, QWidget
from common.i18n import tr
from common.i18n.widgets import QComboBox, QLabel, QPushButton, QPlainTextEdit
from common.qt.module_page import ModulePage
from basic.log.viewer import LogViewer
from .history import STATES
from .views import TaskFlowView, parameter_summary
from .schema import node_display_name


class RunFlowView(TaskFlowView):
    TRAVEL_TIME = 0.45

    def __init__(self):
        super().__init__()
        self._flow_timer = QTimer(self)
        self._flow_timer.setInterval(25)
        self._flow_timer.timeout.connect(self._advance_flow)
        self._node_arrivals = {}
        self._execution_buttons = []

    def set_step_state(self, index, state, started=None):
        if state == "running" and self._states.get(index) != "running":
            elapsed = max(0, time() - started) if started is not None else 0
            self._node_arrivals[index] = monotonic() - elapsed
        elif state != "running":
            self._node_arrivals.pop(index, None)
        super().set_step_state(index, state)
        if self.isVisible():
            self._advance_flow()

    def showEvent(self, event):
        super().showEvent(event)
        self._advance_flow()

    def hideEvent(self, event):
        self._flow_timer.stop()
        super().hideEvent(event)

    def _advance_flow(self):
        now = monotonic()
        ages = {index: now - started for index, started in self._node_arrivals.items()}
        for index, age in ages.items():
            if index < len(self._nodes):
                node = self._nodes[index]
                node.active_seconds = age
                if node.upload_percent is None:
                    node.update()
        for edge in self._edges:
            age = ages.get(edge.endpoints[1].data(0))
            progress = age / self.TRAVEL_TIME if edge.flowing and age is not None and age < self.TRAVEL_TIME else None
            if edge.flow_progress != progress:
                edge.flow_progress = progress
                edge.update()
        if not ages:
            self._flow_timer.stop()
        elif not self._flow_timer.isActive():
            self._flow_timer.start()

    def add_execution_actions(self, header, execute):
        self.run_from_requested.connect(lambda index: execute(start_at=index))
        self.run_only_requested.connect(lambda indexes: execute(indexes=indexes))

        for label, request in (
            ("从此节点开始执行", lambda index: self.run_from_requested.emit(index)),
            ("仅执行此节点", lambda index: self.run_only_requested.emit((index,))),
        ):
            button = QPushButton(tr(label))
            button.clicked.connect(lambda _checked=False, send=request: self._request_selected_step(send))
            header.addWidget(button)
            self._execution_buttons.append(button)
        self.step_selected.connect(self.refresh_execution_actions)
        self.refresh_execution_actions()

    def _request_selected_step(self, request):
        indexes = self.selected_step_indexes()
        if self.run_actions_enabled and len(indexes) == 1:
            request(indexes[0])

    def refresh_execution_actions(self, _index=None):
        enabled = self.run_actions_enabled and len(self.selected_step_indexes()) == 1
        for button in self._execution_buttons:
            button.setEnabled(enabled)


class _RunParameters(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("taskPanel")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.steps = ()
        self.selected_step = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        heading = QLabel(tr("流程参数"))
        heading.setObjectName("panelHeading")
        layout.addWidget(heading)
        self.preview = QPlainTextEdit()
        self.preview.setObjectName("taskParameterPreview")
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText(tr("选择节点以查看参数"))
        layout.addWidget(self.preview, 1)
        self.hide()

    def display_steps(self, steps):
        self.steps = steps
        self.select_step(-1)

    def select_step(self, index):
        self.selected_step = index if 0 <= index < len(self.steps) else None
        self._refresh()
        self.setVisible(self.selected_step is not None)

    def _refresh(self):
        text = parameter_summary(self.steps, self.selected_step) if self.selected_step is not None else ""
        self.preview.setPlainText(text)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange and hasattr(self, "preview"):
            self._refresh()


def _split_flow(flow, parameters):
    split = QSplitter(Qt.Orientation.Horizontal)
    split.setChildrenCollapsible(False)
    split.addWidget(flow)
    split.addWidget(parameters)
    split.setStretchFactor(0, 1)
    split.setSizes([720, 300])
    return split


class TaskExecutionPage(ModulePage):
    fills_panel_workspace = True
    workspace_numbered = True

    def __init__(self, name, document, execute):
        super().__init__()
        self.setObjectName("taskEditor")
        self.setWindowTitle(name)
        self.workspace_item_id = name
        self.run_page = None
        self.stack = QStackedLayout(self)
        preview = QWidget()
        self.stack.addWidget(preview)
        layout = QVBoxLayout(preview)
        header = QHBoxLayout()
        title = QLabel(name)
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch()
        self.execute_button = QPushButton(tr("执行"))
        self.execute_button.clicked.connect(lambda _checked=False: execute())
        self.flow = RunFlowView()
        self.flow.set_editable(False)
        self.flow.show_missing_parameters = True
        self.flow.run_actions_enabled = True
        self.flow.add_execution_actions(header, execute)
        header.addWidget(self.execute_button)
        layout.addLayout(header)
        self.parameters = _RunParameters()
        self.flow.step_selected.connect(self.parameters.select_step)
        layout.addWidget(_split_flow(self.flow, self.parameters), 1)
        self.display_workflow(document)

    def display_workflow(self, document):
        self.document = document
        self.execute_button.setEnabled(bool(document["steps"]))
        self.flow.display_steps(document["steps"], graph=document)
        self.parameters.display_steps(document["steps"])
        self.flow.center_flow()
        self.flow.refresh_execution_actions()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange and hasattr(self, "document"):
            self.flow.display_steps(
                self.document["steps"], self.parameters.selected_step, graph=self.document,
            )
            self.flow.refresh_execution_actions()

    @property
    def run(self):
        return self.run_page.run if self.run_page is not None else None

    def workspace_background_active(self) -> bool:
        return self.run is not None and self.run.active

    def can_duplicate_panel(self) -> bool:
        return True

    def show_run(self, page):
        if self.run_page is not None:
            self.stack.removeWidget(self.run_page)
            self.run_page.deleteLater()
        self.run_page = page
        self.stack.addWidget(page)
        self.stack.setCurrentWidget(page)
        page.close_requested.connect(self.close_requested.emit)


class TaskRunPage(ModulePage):
    fills_panel_workspace = True

    def __init__(self, manager, run, *, execute, back=None, parent=None):
        super().__init__(parent)
        self.manager, self.run = manager, run
        self.close_after_stop = False
        self.setObjectName("taskEditor")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        header = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("pageTitle")
        header.addWidget(self.title)
        header.addStretch()
        self.status = QLabel()
        header.addWidget(self.status)
        self.resolve = QPushButton(tr("解决冲突"))
        self.resolve.clicked.connect(self._resolve)
        header.addWidget(self.resolve)
        self.stop_button = QPushButton(tr("停止"))
        self.stop_button.clicked.connect(lambda: manager.stop(run))
        header.addWidget(self.stop_button)
        self.execute_button = QPushButton(tr("执行"))
        self.execute_button.clicked.connect(lambda _checked=False: execute())
        self.flow = RunFlowView()
        self.flow.set_editable(False)
        self.flow.add_execution_actions(header, execute)
        header.addWidget(self.execute_button)
        if back is not None:
            back_button = QPushButton(tr("返回任务编辑"))
            back_button.clicked.connect(back)
            header.addWidget(back_button)
        self.show_output_button = QPushButton(tr("显示执行输出"))
        self.show_output_button.clicked.connect(lambda: self._set_output_visible(True))
        self.show_output_button.hide()
        header.addWidget(self.show_output_button)
        layout.addLayout(header)
        split = QSplitter(Qt.Orientation.Vertical)
        self.flow.display_steps(run.document["steps"], graph=run.document)
        self.flow.center_flow()
        self.flow.step_selected.connect(self._select_step)
        self.parameters = _RunParameters()
        self.parameters.display_steps(run.document["steps"])
        split.addWidget(_split_flow(self.flow, self.parameters))
        output_header = QHBoxLayout()
        output_header.addWidget(QLabel(tr("执行输出")))
        output_header.addStretch()
        self.viewer = LogViewer(self, output_header)
        self.viewer.text.setMaximumBlockCount(10000)
        self.filter = QComboBox()
        self.filter.addItem(tr("全部步骤"), None)
        for index in run.states:
            self.filter.addItem(tr("第 {0} 步：{1}", index + 1, node_display_name(run.document["steps"][index])), index)
        self.filter.currentIndexChanged.connect(self._filter_output)
        output_header.insertWidget(1, self.filter)
        close_output = QPushButton(tr("关闭"))
        close_output.clicked.connect(lambda: self._set_output_visible(False))
        output_header.addWidget(close_output)
        self.viewer.layout().insertLayout(0, output_header)
        split.addWidget(self.viewer)
        split.setSizes([500, 250])
        layout.addWidget(split, 1)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.summary)
        manager.changed.connect(self._changed)
        manager.output_received.connect(self._output)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()
        self._filter_output()

    def refresh(self):
        run = self.run
        state = STATES[run.record["state"]]
        if run.active and run.runner.stop.is_set():
            state = "正在停止，请等待执行结束"
        elif run.conflict_dialog is not None:
            state = "等待处理"
        title = tr("{0} #{1}", run.task_name, run.number)
        self.title.setText(title)
        self.setWindowTitle(tr("{0} · {1}", title, tr(state)))
        completed = sum(value in {"success", "failed", "stopped"} for value in run.states.values())
        elapsed = max(0, int((run.record["finished"] or time()) - run.record["started"]))
        self.status.setText(tr("{0} · 已结束 {1}/{2} 步 · {3} 秒", tr(state), completed, len(run.states), elapsed))
        self.stop_button.setVisible(run.active)
        self.execute_button.setEnabled(not run.active)
        self.flow.run_actions_enabled = not run.active
        self.flow.refresh_execution_actions()
        self.stop_button.setEnabled(run.active and not run.runner.stop.is_set())
        self.resolve.setVisible(run.conflict_dialog is not None)
        for index in range(len(run.document["steps"])):
            state = run.states.get(index, "excluded")
            node = self.flow._nodes[index]
            if state == "running" and node.wait_step:
                node.wait_duration = int(run.document["steps"][index]["properties"].get("SECONDS", "1"))
            percent = run.upload_progress.get(index)
            if node.upload_percent != percent:
                node.upload_percent = percent
                node.update()
            if self.flow._states.get(index) != state:
                self.flow.set_step_state(index, state, run.record["steps"][index].get("started"))
        if not run.active:
            self.timer.stop()
            groups = {}
            for index, value in run.states.items():
                label = STATES.get(value, value)
                groups.setdefault(label, []).append(str(index + 1))
            self.summary.setText("\n".join(str(tr("{0}：{1}", tr(label), ", ".join(numbers))) for label, numbers in groups.items()) + "\n" + run.record["message"])
        self.summary.setVisible(not run.active)

    def _changed(self, run):
        if run is not self.run:
            return
        self.refresh()
        if self.close_after_stop and not run.active:
            self.close_requested.emit()

    def _output(self, run, index, text):
        if run is self.run and (self.filter.currentData() is None or self.filter.currentData() == index):
            self.viewer.text.appendPlainText(text)

    def _filter_output(self, *_args):
        index = self.filter.currentData()
        self.viewer.text.setPlainText("\n".join(text for step, text in self.run.events if index is None or step == index))

    def _set_output_visible(self, visible):
        self.viewer.setVisible(visible)
        self.show_output_button.setVisible(not visible)

    def _select_step(self, index):
        self.parameters.select_step(index)
        position = 0 if index < 0 else self.filter.findData(index)
        if position >= 0:
            self.filter.setCurrentIndex(position)

    def _resolve(self):
        dialog = self.run.conflict_dialog
        if dialog is not None:
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()

    def can_hide(self):
        if not self.run.active:
            return True
        dialog = QMessageBox(self)
        dialog.setWindowTitle(tr("任务正在执行"))
        dialog.setText(tr("选择关闭执行标签后的操作"))
        background = dialog.addButton(tr("后台继续"), QMessageBox.ButtonRole.AcceptRole)
        stop = dialog.addButton(tr("停止并关闭"), QMessageBox.ButtonRole.DestructiveRole)
        dialog.addButton(QMessageBox.StandardButton.Cancel)
        dialog.exec()
        if dialog.clickedButton() is stop and not self.run.active:
            return True
        if dialog.clickedButton() is stop:
            self.close_after_stop = True
            self.manager.stop(self.run)
        return dialog.clickedButton() is background

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange and hasattr(self, "timer"):
            self.flow.display_steps(
                self.run.document["steps"], self.parameters.selected_step, graph=self.run.document,
            )
            self.refresh()
