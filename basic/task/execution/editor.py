"""Execution parameter form and isolated trial dialog."""
from pathlib import Path
from copy import deepcopy
from threading import Event, Thread
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QMessageBox, QSpinBox, QVBoxLayout, QWidget
from basic.log.viewer import LogViewer
from common.i18n import tr
from common.i18n.widgets import QDialog, QLabel, QLineEdit, QPushButton
from .code_editor import CodeEditor
from .schema import CHOICES, FIELD_LABELS, STEP_LABELS, defaults, effective_kind, validate, working_directory_required
from .templates import script_template
from ..dialog_style import PARAMETER_SIDE_PADDING, parameter_dialog_layout


class ProbeWorker(QObject):
    message = Signal(object)
    finished = Signal(bool, object)

    def __init__(self, services, parent=None):
        super().__init__(parent)
        self.services = services
        self.stop = Event()

    def start(self, kind, values):
        self.stop.clear()
        Thread(target=self._run, args=(kind, deepcopy(values)), daemon=True).start()

    def _run(self, kind, values):
        from .engine import ExecutionEngine
        from ..upload import STEP_LABELS as UPLOAD_LABELS, UploadEngine
        try:
            engine = UploadEngine if kind in UPLOAD_LABELS else ExecutionEngine
            engine(self.services, self.message.emit, self.stop).execute(kind, values)
        except Exception as error:
            self.finished.emit(False, str(error))
        else:
            self.finished.emit(True, tr("试运行成功"))


class ProbeDialog(QDialog):
    def __init__(self, services, kind, values, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("试运行当前步骤"))
        self.resize(850, 520)
        self.running = True
        service = services.log_service if services is not None else None
        self._log_writer = service.open_session("task", "trial") if service is not None else None
        self.worker = ProbeWorker(services, self)
        layout = QVBoxLayout(self)
        log_viewer = LogViewer(self)
        self.output = log_viewer.text
        self.output.setMaximumBlockCount(3000)
        layout.addWidget(log_viewer, 1)
        row = QHBoxLayout()
        self.stop_button = QPushButton(tr("停止"))
        self.stop_button.clicked.connect(self._request_stop)
        row.addStretch()
        row.addWidget(self.stop_button)
        self.close_button = QPushButton(tr("关闭"))
        self.close_button.setEnabled(False)
        self.close_button.clicked.connect(self.accept)
        row.addWidget(self.close_button)
        layout.addLayout(row)
        self.worker.message.connect(self._log)
        self.worker.finished.connect(self._done)
        self.worker.start(kind, values)

    def _log(self, text):
        self.output.appendPlainText(str(text))
        if self._log_writer is not None:
            self._log_writer.event("task", str(text))

    def _done(self, success, message):
        self.running = False
        self.success = success
        self._log(message)
        if self._log_writer is not None:
            self._log_writer.close()
            self._log_writer = None
        self.stop_button.setEnabled(False)
        self.close_button.setEnabled(True)

    def _request_stop(self):
        if self.running and not self.worker.stop.is_set():
            self.worker.stop.set()
            self.stop_button.setEnabled(False)
            self._log(tr("正在停止，请等待执行结束"))

    def reject(self):
        if self.running:
            self._request_stop()
        else:
            super().reject()

    def closeEvent(self, event):
        if self.running:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)


class ExecutionParameterEditor(QWidget):
    changed = Signal(object)

    def __init__(self, services=None, parent=None, *, side_padding=0):
        super().__init__(parent)
        self.services = services
        self.kind = None
        self._loading = False
        self._script_drafts = {}
        self._script_interpreter = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.form = QFormLayout()
        self.form.setContentsMargins(side_padding, 0, side_padding, 0)
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        self.fields, self.rows = {}, {}
        for key, label in FIELD_LABELS.items():
            if key in {"EXECUTION_MODE", "COMMAND", "SCRIPT_CONTENT", "ARGUMENTS", "TIMEOUT"}:
                continue
            if key in CHOICES or key == "SERVER":
                field = QComboBox()
                field.currentIndexChanged.connect(self._interpreter_changed if key == "INTERPRETER" else self._changed)
            else:
                field = QLineEdit()
                field.textEdited.connect(self._changed)
            self.fields[key] = field
            caption = QLabel(tr(label))
            container = QWidget()
            row = QHBoxLayout(container)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(field, 1)
            if key == "INTERPRETER":
                timeout = QSpinBox()
                timeout.setRange(0, 86400)
                timeout.setFixedWidth(92)
                timeout.valueChanged.connect(self._changed)
                self.fields["TIMEOUT"] = timeout
                row.addWidget(QLabel(tr(FIELD_LABELS["TIMEOUT"])))
                row.addWidget(timeout)
            if key == "WORKING_DIRECTORY":
                self.choose_directory = QPushButton(tr("选择"))
                self.choose_directory.clicked.connect(self._browse_directory)
                row.addWidget(self.choose_directory)
            self.form.addRow(caption, container)
            self.rows[key] = (caption, container)
        layout.addLayout(self.form)
        editor_header = QHBoxLayout()
        editor_header.setContentsMargins(side_padding, 0, side_padding, 0)
        self.code_caption = QLabel()
        editor_header.addWidget(self.code_caption, 1)
        button = QPushButton(tr("试运行"))
        button.setAutoDefault(False)
        button.clicked.connect(self._probe)
        editor_header.addWidget(button)
        layout.addLayout(editor_header)
        self.code_editor = CodeEditor()
        self.code_editor.setMinimumHeight(150)
        self.code_editor.textChanged.connect(self._changed)
        layout.addWidget(self.code_editor, 1)
        self.cursor_position = QLabel()
        self.cursor_position.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.cursor_position.setContentsMargins(side_padding, 0, side_padding, 0)
        self.code_editor.cursorPositionChanged.connect(self._update_cursor_position)
        self._update_cursor_position()
        layout.addWidget(self.cursor_position)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setContentsMargins(side_padding, 0, side_padding, 0)
        layout.addWidget(self.hint)
        self.result = QLabel(tr("尚未试运行"))
        self.result.setWordWrap(True)
        self.result.setContentsMargins(side_padding, 0, side_padding, 0)
        layout.addWidget(self.result)

    def display_step(self, step):
        self._loading = True
        properties = step.get("properties", {})
        self.kind = effective_kind(step["type"], properties)
        values = defaults(self.kind)
        values.update(properties)
        legacy = (
            self.kind.endswith("SCRIPT") and "SCRIPT_CONTENT" not in properties
            and bool(properties.get("SCRIPT_PATH"))
        )
        legacy_error = False
        if legacy and self.kind.startswith("LOCAL"):
            path = Path(properties["SCRIPT_PATH"]).expanduser()
            if not path.is_absolute():
                path = Path(values["WORKING_DIRECTORY"]).expanduser() / path if values["WORKING_DIRECTORY"] else Path.home() / path
            try:
                values["SCRIPT_CONTENT"] = path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError):
                legacy_error = True
        elif legacy:
            legacy_error = True
        if "SCRIPT_CONTENT" not in values:
            values["SCRIPT_CONTENT"] = script_template(values["INTERPRETER"])[0] if self.kind.endswith("SCRIPT") and not legacy else ""
        for key, field in self.fields.items():
            if isinstance(field, QComboBox):
                field.clear()
                if key == "SERVER":
                    names = self.services.store.list_names() if self.services else []
                    if values[key] and values[key] not in names:
                        names.append(values[key])
                    field.addItem(str(tr("请选择服务器")), "")
                    for name in names:
                        field.addItem(name, name)
                else:
                    for value, label in CHOICES[key].items():
                        if key == "INTERPRETER" and self.kind.startswith("REMOTE") and value not in {"bash", "sh"}:
                            continue
                        field.addItem(str(tr(label)), value)
                field.setCurrentIndex(max(0, field.findData(values[key])))
            elif isinstance(field, QSpinBox):
                field.setValue(int(values[key]))
            else:
                field.setText(values[key])
        self.code_editor.setPlainText(values[self._code_key()])
        self._script_interpreter = self.fields["INTERPRETER"].currentData()
        self._script_drafts.clear()
        self._loading = False
        self._visibility()
        self.result.setText(tr("旧任务请粘贴脚本内容后保存，原配置尚未修改") if legacy_error else tr("尚未试运行"))

    def _code_key(self):
        return "SCRIPT_CONTENT" if self.kind.endswith("SCRIPT") else "COMMAND"

    def _update_cursor_position(self):
        cursor = self.code_editor.textCursor()
        self.cursor_position.setText(tr("第 {0} 行，第 {1} 列", cursor.blockNumber() + 1, cursor.positionInBlock() + 1))

    def _set_script_text(self, text):
        self._loading = True
        try:
            self.code_editor.setPlainText(text)
        finally:
            self._loading = False

    def _interpreter_changed(self, *_args):
        if self._loading or self.kind is None:
            return
        if self.kind.endswith("SCRIPT"):
            self._script_drafts[self._script_interpreter] = self.code_editor.toPlainText()
            self._script_interpreter = self.fields["INTERPRETER"].currentData()
            draft = self._script_drafts.get(self._script_interpreter, "")
            if not draft.strip():
                draft = script_template(self._script_interpreter)[0]
            self._set_script_text(draft)
        self._changed()

    def _visibility(self):
        remote = self.kind.startswith("REMOTE")
        script = self.kind.endswith("SCRIPT")
        for key, widgets in self.rows.items():
            for widget in widgets:
                widget.setVisible(key != "SERVER" or remote)
        self.choose_directory.setVisible(not remote)
        directory_required = working_directory_required(self.kind)
        self.rows["WORKING_DIRECTORY"][0].setText(
            tr("工作目录（必填）" if directory_required else FIELD_LABELS["WORKING_DIRECTORY"])
        )
        self.fields["WORKING_DIRECTORY"].setPlaceholderText(
            tr("请输入或选择工作目录" if directory_required else "留空使用登录用户主目录")
        )
        self.fields["TIMEOUT"].setToolTip(str(tr("0 表示不限制执行时间")))
        self.fields["INTERPRETER"].setToolTip(str(tr(
            "Sh：适合通用 POSIX 脚本。\nBash：支持数组、[[ … ]] 等扩展语法，需要服务器安装 Bash。"
            if remote else
            "CMD：Windows 批处理（.bat / .cmd）。\nPowerShell：PowerShell 脚本（.ps1）。\n"
            "Git Bash / Bash：支持数组、[[ … ]] 等 Bash 语法。\nSh：适合通用 POSIX 脚本。\n"
            "Windows 上使用 Bash 或 Sh 需要本机有对应的解释器，例如 Git for Windows。"
        )))
        self.code_caption.setText(tr(FIELD_LABELS[self._code_key()]))
        self.code_editor.setPlaceholderText(
            "" if script else str(tr("每行一条完整命令，回车继续；按顺序执行，失败即停止"))
        )
        if script:
            self.hint.setText(tr("内容按一个完整脚本执行。试运行会真实执行。"))
        else:
            self.hint.setText(tr("此旧节点沿用命令模式。试运行会真实执行。"))

    def values(self):
        values = {"EXECUTION_MODE": "script" if self.kind.endswith("SCRIPT") else "command"}
        for key, field in self.fields.items():
            values[key] = field.currentData() if isinstance(field, QComboBox) else str(field.value()) if isinstance(field, QSpinBox) else field.text()
        values[self._code_key()] = self.code_editor.toPlainText()
        values["ARGUMENTS"] = "[]"
        return values

    def _changed(self, *_args):
        if self._loading or self.kind is None:
            return
        self.result.setText(tr("参数已修改，请重新试运行"))
        self.changed.emit(self.values())

    def _browse_directory(self):
        value = QFileDialog.getExistingDirectory(self, tr("选择目录"))
        if value:
            self.fields["WORKING_DIRECTORY"].setText(value)
            self._changed()

    def _probe(self):
        try:
            values = validate(self.kind, self.values())
        except ValueError as error:
            QMessageBox.warning(self, tr("任务"), str(error))
            return
        if QMessageBox.question(self, tr("试运行当前步骤"), tr("这会真实执行当前命令或脚本，可能修改文件或服务，是否继续？"), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            dialog = ProbeDialog(self.services, self.kind, values, self)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, tr("任务"), str(error))
            return
        dialog.exec()
        self.result.setText(tr("试运行成功") if getattr(dialog, "success", False) else tr("试运行失败，请查看日志"))
        dialog.deleteLater()


class ExecutionStepDialog(QDialog):
    def __init__(self, services, kind, properties=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr(STEP_LABELS[kind]))
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint)
        self.resize(880, 700)
        layout = parameter_dialog_layout(self, tr(STEP_LABELS[kind]), full_width=True)
        self.editor = ExecutionParameterEditor(services, self, side_padding=PARAMETER_SIDE_PADDING)
        if properties is None:
            properties = {"INTERPRETER": "sh"} if kind.startswith("REMOTE") else {}
        self.editor.display_step({"type": kind, "properties": properties})
        self.editor.form.setHorizontalSpacing(18)
        self.editor.form.setVerticalSpacing(10)
        layout.addWidget(self.editor, 1)
        row = QHBoxLayout()
        row.setContentsMargins(PARAMETER_SIDE_PADDING, 0, PARAMETER_SIDE_PADDING, 0)
        row.addStretch()
        for label, callback in (("确认", self._confirm), ("取消", self.reject)):
            button = QPushButton(tr(label))
            button.setMinimumWidth(88)
            button.setAutoDefault(False)
            if label == "确认":
                button.setObjectName("parameterConfirm")
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)

    def properties(self):
        return self.editor.values()

    def _confirm(self):
        try:
            validate(self.editor.kind, self.properties())
        except ValueError as error:
            QMessageBox.warning(self, tr("任务"), str(error))
        else:
            self.accept()
