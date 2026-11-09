"""Inline editor for the selected workflow step."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QScrollArea, QVBoxLayout

from common.i18n import tr
from common.i18n.widgets import QLabel, QLineEdit, QPushButton

from .git.schema import FIELD_LABELS, POLICIES, STEP_FIELDS
from .execution.editor import ExecutionParameterEditor
from .shell_panel import ShellPanelEditor
from .health import HealthParameterEditor
from .wait import WaitParameterEditor
from .upload import STEP_LABELS as UPLOAD_LABELS, UploadParameterEditor
from .execution.schema import STEP_LABELS as EXECUTION_LABELS


class TaskParameterEditor(QFrame):
    changed = Signal(object)

    def __init__(self, parent=None, services=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.notice = QLabel(tr("选择节点后可直接修改参数"))
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.form_widget = QFrame()
        form = QFormLayout(self.form_widget)
        form.setContentsMargins(0, 0, 0, 0)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.fields = {}
        self.rows = {}
        self._step_type = None
        for key, label in FIELD_LABELS.items():
            if key == "CONFLICT_POLICY":
                continue
            field = QLineEdit()
            if key.endswith("BRANCH"):
                field.setPlaceholderText(tr("选填，留空使用对应目录的当前分支"))
            self.fields[key] = field
            field.textEdited.connect(self._changed)
            row = QHBoxLayout()
            row.addWidget(field, 1)
            if key.endswith("PROJECT_PATH"):
                button = QPushButton(tr("选择目录"))
                button.clicked.connect(lambda _checked=False, control=field: self._choose(control))
                row.addWidget(button)
            container = QFrame()
            container.setLayout(row)
            row.setContentsMargins(0, 0, 0, 0)
            caption = QLabel(tr(label))
            self.rows[key] = (caption, container)
            form.addRow(caption, container)
        self.policy = QComboBox()
        for value, label in POLICIES.items():
            self.policy.addItem(str(tr(label)), value)
        self.policy.currentIndexChanged.connect(self._changed)
        self.policy_label = QLabel(tr("冲突处理"))
        form.addRow(self.policy_label, self.policy)
        layout.addWidget(self.form_widget)
        self.execution = ExecutionParameterEditor(services, self)
        self.execution.changed.connect(self.changed.emit)
        self.execution_scroll = QScrollArea()
        self.execution_scroll.setWidgetResizable(True)
        self.execution_scroll.setWidget(self.execution)
        layout.addWidget(self.execution_scroll, 1)
        self.upload = UploadParameterEditor(services, self)
        self.upload.changed.connect(self.changed.emit)
        layout.addWidget(self.upload)
        self.wait = WaitParameterEditor(self)
        self.wait.changed.connect(self.changed.emit)
        layout.addWidget(self.wait)
        self.health = HealthParameterEditor(services, self)
        self.health.changed.connect(self.changed.emit)
        layout.addWidget(self.health)
        self.shell_panel = ShellPanelEditor(services, self)
        self.shell_panel.changed.connect(self.changed.emit)
        layout.addWidget(self.shell_panel)
        layout.addStretch()
        self.display_step(None)

    def display_step(self, step, editable=True):
        self._step_type = step["type"] if step is not None else None
        remote_step = self._step_type in EXECUTION_LABELS
        self.execution_scroll.setVisible(remote_step)
        self.execution.setEnabled(editable)
        upload_step = self._step_type in UPLOAD_LABELS
        self.upload.setVisible(upload_step)
        self.upload.setEnabled(editable)
        wait_step = self._step_type == "WAIT"
        self.wait.setVisible(wait_step)
        self.wait.setEnabled(editable)
        health_step = self._step_type == "HEALTH_CHECK"
        self.health.setVisible(health_step)
        self.health.setEnabled(editable)
        shell_step = self._step_type == "OPEN_SHELL"
        self.shell_panel.setVisible(shell_step)
        self.shell_panel.setEnabled(editable)
        if shell_step:
            self.shell_panel.display_step(step)
            self.form_widget.hide()
            self.notice.hide()
            return
        if health_step:
            self.health.display_step(step)
            self.form_widget.hide()
            self.notice.hide()
            return
        if wait_step:
            self.wait.display_step(step)
            self.form_widget.hide()
            self.notice.hide()
            return
        if upload_step:
            self.upload.display_step(step)
            self.form_widget.hide()
            self.notice.hide()
            return
        if remote_step:
            self.execution.display_step(step)
            self.form_widget.hide()
            self.notice.hide()
            return
        self.policy_label.setVisible(self._step_type != "MAVEN_BUILD")
        self.policy.setVisible(self._step_type != "MAVEN_BUILD")
        supported = self._step_type in STEP_FIELDS
        self.form_widget.setVisible(supported)
        self.form_widget.setEnabled(editable)
        self.notice.setVisible(not supported)
        for key, field in self.fields.items():
            for widget in self.rows[key]:
                widget.setVisible(key in STEP_FIELDS.get(self._step_type, ()))
            value = step.get("properties", {}).get(key, "600" if key == "BUILD_TIMEOUT" else "artifact" if key == "ARTIFACT_NAME" else "") if supported else ""
            field.setText(value if isinstance(value, str) else "")
        self.policy.blockSignals(True)
        for index, label in enumerate(POLICIES.values()):
            self.policy.setItemText(index, str(tr(label)))
        policy = step.get("properties", {}).get("CONFLICT_POLICY", "rollback") if supported else "rollback"
        self.policy.setCurrentIndex(max(0, self.policy.findData(policy)))
        self.policy.blockSignals(False)

    def values(self):
        if self._step_type == "OPEN_SHELL":
            return self.shell_panel.values()
        if self._step_type == "HEALTH_CHECK":
            return self.health.values()
        if self._step_type == "WAIT":
            return self.wait.values()
        if self._step_type in UPLOAD_LABELS:
            return self.upload.values()
        if self._step_type in EXECUTION_LABELS:
            return self.execution.values()
        values = {key: self.fields[key].text().strip() for key in STEP_FIELDS.get(self._step_type, ())}
        if self._step_type != "MAVEN_BUILD":
            values["CONFLICT_POLICY"] = self.policy.currentData()
        return values

    def _choose(self, field):
        directory = QFileDialog.getExistingDirectory(self, tr("选择目录"), field.text())
        if directory:
            field.setText(directory)
            self._changed()

    def _changed(self, *_args):
        if self._step_type in STEP_FIELDS:
            self.changed.emit(self.values())
