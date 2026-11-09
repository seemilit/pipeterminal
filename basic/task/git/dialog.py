"""Parameters for Git workflow actions."""

from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QMessageBox, QScrollArea
from common.i18n import tr
from common.i18n.widgets import QDialog, QLabel, QPushButton
from ..parameters import TaskParameterEditor
from ..dialog_style import parameter_dialog_layout
from .schema import STEP_HINTS, STEP_LABELS
from .build import validate_build


class GitMergeDialog(QDialog):
    def __init__(self, properties=None, parent=None, step_type="MERGE_BRANCH"):
        super().__init__(parent)
        self.setWindowTitle(tr(STEP_LABELS[step_type]))
        self.setMinimumWidth(620)
        self.resize(760, 560)
        self.step_type = step_type
        layout = parameter_dialog_layout(self, tr(STEP_LABELS[step_type]))
        self.editor = TaskParameterEditor()
        self.editor.display_step({"type": step_type, "properties": properties or {}})
        form = self.editor.form_widget.layout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(14)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.editor)
        layout.addWidget(scroll, 1)
        hint = QLabel(tr(STEP_HINTS[step_type]))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QHBoxLayout()
        buttons.addStretch()
        confirm = QPushButton(tr("确认"))
        confirm.setObjectName("parameterConfirm")
        confirm.setMinimumWidth(88)
        confirm.setDefault(True)
        confirm.clicked.connect(self._confirm)
        cancel = QPushButton(tr("取消"))
        cancel.setMinimumWidth(88)
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(confirm)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

    def properties(self):
        return self.editor.values()

    def _confirm(self):
        values = self.properties()
        if self.step_type == "MAVEN_BUILD":
            try:
                validate_build(values)
            except ValueError as error:
                QMessageBox.warning(self, tr("任务"), str(error))
                return
        required = ("SOURCE_PROJECT_PATH", "TARGET_PROJECT_PATH") if self.step_type == "MERGE_BRANCH" else ("PROJECT_PATH",)
        if any(not values[key] for key in required):
            QMessageBox.warning(self, tr("任务"), tr("请填写项目目录"))
            return
        self.accept()
