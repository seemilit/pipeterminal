"""Repeat read-only server checks until consecutive successes are reached."""
from time import monotonic
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFormLayout, QHBoxLayout, QListView, QMessageBox, QPlainTextEdit, QSpinBox, QVBoxLayout, QWidget
from common.i18n import tr
from common.i18n.widgets import QDialog, QLabel, QPushButton
from .dialog_style import parameter_dialog_layout
from .execution.engine import CommandExitError, ExecutionEngine

FIELD_LABELS = {"SERVER": "服务器配置", "HEALTH_COMMAND": "检查命令", "HEALTH_TIMEOUT": "最长等待（秒）", "HEALTH_INTERVAL": "检查间隔（秒）", "SUCCESS_COUNT": "连续成功次数"}
DEFAULTS = {"SERVER": "", "HEALTH_COMMAND": "", "HEALTH_TIMEOUT": "120", "HEALTH_INTERVAL": "3", "SUCCESS_COUNT": "2"}


def validate_health(properties):
    values = {**DEFAULTS, **properties}
    if any(not isinstance(values[key], str) or "\0" in values[key] for key in DEFAULTS) or not values["SERVER"].strip() or not values["HEALTH_COMMAND"].strip():
        raise ValueError(tr("请选择服务器并填写检查命令"))
    for key in ("HEALTH_TIMEOUT", "HEALTH_INTERVAL", "SUCCESS_COUNT"):
        try:
            number = int(values[key])
        except ValueError:
            raise ValueError(tr("健康检查参数必须为 1～86400 的整数")) from None
        if not 1 <= number <= 86400:
            raise ValueError(tr("健康检查参数必须为 1～86400 的整数"))
    return values


def execute_health(properties, services, log, stop):
    values = validate_health(properties)
    deadline = monotonic() + int(values["HEALTH_TIMEOUT"])
    successes = attempts = 0
    required = int(values["SUCCESS_COUNT"])
    while monotonic() < deadline:
        if stop.is_set():
            raise RuntimeError(tr("执行已停止"))
        remaining = int(deadline - monotonic())
        if remaining < 1:
            break
        attempts += 1
        try:
            ExecutionEngine(services, log, stop).execute("REMOTE_COMMAND", {
                "SERVER": values["SERVER"], "INTERPRETER": "sh", "COMMAND": values["HEALTH_COMMAND"],
                "TIMEOUT": str(min(30, remaining)),
            })
        except CommandExitError:
            successes = 0
            log(tr("第 {0} 次健康检查未通过", attempts))
        else:
            if stop.is_set():
                raise RuntimeError(tr("执行已停止"))
            if monotonic() >= deadline:
                break
            successes += 1
            log(tr("健康检查通过（{0}/{1}）", successes, required))
            if successes >= required:
                return
        remaining = deadline - monotonic()
        if remaining > 0 and stop.wait(min(int(values["HEALTH_INTERVAL"]), remaining)):
            raise RuntimeError(tr("执行已停止"))
    raise RuntimeError(tr("健康检查在 {0} 秒内未通过", values["HEALTH_TIMEOUT"]))


class HealthParameterEditor(QWidget):
    changed = Signal(object)

    def __init__(self, services=None, parent=None):
        super().__init__(parent)
        self.services = services
        self._loading = False
        self.fields = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setVerticalSpacing(10)
        for key, label in FIELD_LABELS.items():
            if key == "SERVER":
                field = QComboBox()
                field.setView(QListView(field))
                field.setMaxVisibleItems(12)
                field.setStyleSheet("QComboBox { combobox-popup: 0; }")
                field.currentIndexChanged.connect(self._changed)
            elif key == "HEALTH_COMMAND":
                field = QPlainTextEdit()
                field.setMinimumHeight(120)
                field.textChanged.connect(self._changed)
            else:
                field = QSpinBox()
                field.setRange(1, 86400)
                field.valueChanged.connect(self._changed)
            self.fields[key] = field
            form.addRow(QLabel(tr(label)), field)
        layout.addLayout(form)
        hint = QLabel(tr("仅填写可重复执行的查询命令；退出码 0 表示成功。普通失败会重试，超时或连接异常时停止流程。"))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()

    def display_step(self, step):
        self._loading = True
        try:
            values = {**DEFAULTS, **step.get("properties", {})}
            for key, field in self.fields.items():
                if key == "SERVER":
                    field.clear()
                    field.addItem(str(tr("请选择服务器")), "")
                    names = self.services.store.list_names() if self.services else []
                    if values[key] and values[key] not in names:
                        names.append(values[key])
                    for name in names:
                        field.addItem(name, name)
                    field.setCurrentIndex(max(0, field.findData(values[key])))
                elif key == "HEALTH_COMMAND":
                    field.setPlainText(values[key])
                else:
                    field.setValue(int(values[key]))
        finally:
            self._loading = False

    def values(self):
        return {key: field.currentData() or "" if key == "SERVER" else field.toPlainText() if key == "HEALTH_COMMAND" else str(field.value()) for key, field in self.fields.items()}

    def _changed(self, *_args):
        if not self._loading:
            self.changed.emit(self.values())


class HealthDialog(QDialog):
    def __init__(self, services, properties=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("健康检查"))
        self.resize(700, 570)
        layout = parameter_dialog_layout(self, tr("健康检查"))
        self.editor = HealthParameterEditor(services, self)
        self.editor.display_step({"properties": properties or {}})
        layout.addWidget(self.editor, 1)
        row = QHBoxLayout()
        row.addStretch()
        for text, callback in (("确认", self._confirm), ("取消", self.reject)):
            button = QPushButton(tr(text))
            button.setMinimumWidth(88)
            button.setAutoDefault(False)
            if text == "确认":
                button.setObjectName("parameterConfirm")
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)

    def properties(self):
        return self.editor.values()

    def _confirm(self):
        try:
            validate_health(self.properties())
        except ValueError as error:
            QMessageBox.warning(self, tr("健康检查"), str(error))
            return
        self.accept()
