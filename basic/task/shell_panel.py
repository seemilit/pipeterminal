"""Open a real interactive Shell as a GUI action inside a workflow."""
import shlex
from time import monotonic
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QComboBox, QFormLayout, QHBoxLayout, QListView, QMessageBox, QVBoxLayout, QWidget
from shiboken6 import isValid
from common.i18n import tr
from common.i18n.widgets import QDialog, QLabel, QLineEdit, QPushButton
from .dialog_style import parameter_dialog_layout
from .execution.code_editor import CodeEditor


def _startup_command(script):
    if not script.strip():
        return ""
    script = script.rstrip("\n")
    if "\n" not in script and "\t" not in script and len(script.encode("utf-8")) < 2048:
        return script

    # Parse the entire script before any of it can read terminal input.
    # Short continued lines also fit the PTY's line buffer before login is ready.
    arguments = []
    for offset in range(0, len(script), 384):
        part = script[offset:offset + 384]
        part = part.replace("\\", "\\\\").replace("'", r"\047").replace("\n", r"\n").replace("\t", r"\t")
        arguments.append(shlex.quote(part))
    continuation = " \\\n"
    return "eval \"$(printf '%b'" + continuation + continuation.join(arguments) + ")\""


def validate_shell_panel(properties):
    server = properties.get("SERVER", "")
    directory = properties.get("WORKING_DIRECTORY", "")
    script = properties.get("SHELL_COMMAND", "")
    if not isinstance(server, str) or not server.strip():
        raise ValueError(tr("请选择服务器配置"))
    if not isinstance(directory, str) or any(ord(char) < 32 or ord(char) == 127 for char in directory):
        raise ValueError(tr("服务器目录无效"))
    if not isinstance(script, str):
        raise ValueError(tr("执行参数必须是文本且不能包含空字符"))
    script = script.replace("\r\n", "\n").replace("\r", "\n")
    if any((ord(char) < 32 and char not in "\n\t") or ord(char) == 127 for char in script):
        raise ValueError(tr("脚本包含无法发送到终端的控制字符"))
    if len(script.encode("utf-8")) >= 1024 * 1024:
        raise ValueError(tr("粘贴内容超过 1 MB 输入限制"))
    command = _startup_command(script)
    if len(command.encode("utf-8")) >= 1024 * 1024:
        raise ValueError(tr("粘贴内容超过 1 MB 输入限制"))
    return {"SERVER": server, "WORKING_DIRECTORY": directory.strip(), "SHELL_COMMAND": command}


class ShellPanelBridge(QObject):
    def __init__(self, registry, parent=None):
        super().__init__(parent)
        self.registry = registry

    def open(self, request):
        if request["cancel"].is_set():
            request["event"].set()
            return
        try:
            opener = self.registry.get_service("open_shell_panel")
            if opener is None:
                raise ValueError(tr("命令终端不可用"))
            values = validate_shell_panel(request["properties"])
            panel = opener(values["SERVER"], values["SHELL_COMMAND"], directory=values["WORKING_DIRECTORY"])
        except Exception as error:
            request["error"] = str(error)
            request["event"].set()
            return
        deadline = monotonic() + 120
        timer = QTimer(self)
        timer.setInterval(100)
        def poll():
            if not isValid(panel):
                error = tr("Shell 面板已关闭")
            elif request["cancel"].is_set():
                if panel.session.state == "connecting":
                    panel.session.disconnect_session()
                error = tr("执行已停止")
            elif panel.session.state == "connected":
                error = ""
            elif panel.session.state == "idle":
                error = tr("Shell 连接失败，请查看终端日志")
            elif monotonic() >= deadline:
                panel.session.disconnect_session()
                error = tr("打开 Shell 面板超时")
            else:
                return
            request["error"] = str(error)
            request["event"].set()
            timer.stop()
            timer.deleteLater()
        timer.timeout.connect(poll)
        timer.start()
        poll()


class ShellPanelEditor(QWidget):
    changed = Signal(object)

    def __init__(self, services=None, parent=None):
        super().__init__(parent)
        self.services, self._loading = services, False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.server = QComboBox()
        self.server.setView(QListView(self.server))
        self.server.setMaxVisibleItems(12)
        self.server.setStyleSheet("QComboBox { combobox-popup: 0; }")
        self.server.currentIndexChanged.connect(self._changed)
        form.addRow(QLabel(tr("服务器配置")), self.server)
        self.directory = QLineEdit()
        self.directory.setPlaceholderText(tr("选填，例如 /opt/app 或 ~/app"))
        self.directory.textChanged.connect(self._changed)
        form.addRow(QLabel(tr("工作目录")), self.directory)
        layout.addLayout(form)
        layout.addWidget(QLabel(tr("脚本内容")))
        self.command = CodeEditor()
        self.command.setMinimumHeight(140)
        self.command.setPlaceholderText(tr("选填，例如 tail -f /var/log/app.log；留空只打开终端"))
        self.command.textChanged.connect(self._changed)
        layout.addWidget(self.command, 1)
        hint = QLabel(tr("新建并切换到服务器 Shell，连接就绪后保留面板。命令交给交互终端执行，流程不等待命令退出，也不以命令退出码判断成功。"))
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def display_step(self, step):
        self._loading = True
        try:
            values = step.get("properties", {})
            selected = values.get("SERVER", "")
            self.server.clear()
            self.server.addItem(str(tr("请选择服务器")), "")
            names = self.services.store.list_names() if self.services else []
            if selected and selected not in names:
                names.append(selected)
            for name in names:
                self.server.addItem(name, name)
            self.server.setCurrentIndex(max(0, self.server.findData(selected)))
            self.directory.setText(values.get("WORKING_DIRECTORY", ""))
            self.command.setPlainText(values.get("SHELL_COMMAND", ""))
        finally:
            self._loading = False

    def values(self):
        return {
            "SERVER": self.server.currentData() or "",
            "WORKING_DIRECTORY": self.directory.text().strip(),
            "SHELL_COMMAND": self.command.toPlainText(),
        }

    def _changed(self, *_args):
        if not self._loading:
            self.changed.emit(self.values())


class ShellPanelDialog(QDialog):
    def __init__(self, services, properties=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("唤醒服务器"))
        self.resize(760, 540)
        layout = parameter_dialog_layout(self, tr("唤醒服务器"))
        self.editor = ShellPanelEditor(services, self)
        self.editor.display_step({"properties": properties or {}})
        layout.addWidget(self.editor, 1)
        row = QHBoxLayout()
        row.addStretch()
        for text, callback in (("确认", self._confirm), ("取消", self.reject)):
            button = QPushButton(tr(text))
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
            validate_shell_panel(self.properties())
        except ValueError as error:
            QMessageBox.warning(self, tr("唤醒服务器"), str(error))
            return
        self.accept()
