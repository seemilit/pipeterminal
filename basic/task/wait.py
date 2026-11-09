"""An interruptible delay between workflow steps."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QSpinBox, QVBoxLayout, QWidget
from common.i18n import tr
from common.i18n.widgets import QDialog, QLabel, QPushButton
from .dialog_style import parameter_dialog_layout


def wait_seconds(properties):
    value = properties.get("SECONDS", "1")
    if not isinstance(value, str) or not value.isdecimal() or not 1 <= int(value) <= 86400:
        raise ValueError(tr("等待时间必须为 1～86400 秒"))
    return int(value)


def execute_wait(properties, log, stop):
    seconds = wait_seconds(properties)
    log(tr("等待 {0} 秒", seconds))
    if stop.wait(seconds):
        raise RuntimeError(tr("执行已停止"))
    log(tr("等待结束，继续执行"))


class WaitParameterEditor(QWidget):
    changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.seconds = QSpinBox()
        self.seconds.setRange(1, 86400)
        self.seconds.setValue(1)
        self.seconds.valueChanged.connect(lambda _value: self.changed.emit(self.values()))
        form.addRow(QLabel(tr("等待时间（秒）")), self.seconds)
        layout.addLayout(form)
        hint = QLabel(tr("等待指定时间后继续下一步，等待期间可以停止流程。"))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()

    def display_step(self, step):
        self.seconds.blockSignals(True)
        try:
            self.seconds.setValue(wait_seconds(step.get("properties", {})))
        finally:
            self.seconds.blockSignals(False)

    def values(self):
        return {"SECONDS": str(self.seconds.value())}


class WaitDialog(QDialog):
    def __init__(self, properties=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("等待"))
        self.resize(480, 240)
        layout = parameter_dialog_layout(self, tr("等待"))
        self.editor = WaitParameterEditor(self)
        self.editor.display_step({"properties": properties or {}})
        layout.addWidget(self.editor, 1)
        row = QHBoxLayout()
        row.addStretch()
        for text, callback in (("确认", self.accept), ("取消", self.reject)):
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
