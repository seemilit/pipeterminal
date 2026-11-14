"""Workflow uploads reuse the basic SFTP transfer implementation."""
import errno
import posixpath
import stat
from pathlib import Path
from threading import Event
from time import monotonic

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QCheckBox, QRadioButton, QComboBox, QListView, QStyledItemDelegate, QFormLayout, QHBoxLayout, QMessageBox, QVBoxLayout, QWidget
from common.qt.file_dialog import choose_directory, choose_file
from common.i18n import tr
from common.i18n.widgets import QDialog, QLabel, QLineEdit, QPushButton
from .dialog_style import parameter_dialog_layout

STEP_LABELS = {"UPLOAD_JAR": "JAR 包", "UPLOAD_FILE": "文件", "UPLOAD_FOLDER": "文件夹"}
FIELD_LABELS = {"ARTIFACT_NAME": "产物名称", "JAR_FILTER": "JAR 筛选", "UPLOAD_SOURCE": "本地来源", "SERVER": "服务器配置", "UPLOAD_DIRECTORY": "服务器目录", "UPLOAD_CONFLICT": "同名文件处理", "UPLOAD_CREATE_DIRECTORY": "目录不存在时创建"}
POLICIES = {"error": "报错停止", "overwrite": "覆盖"}
DEFAULTS = {"ARTIFACT_NAME": "", "JAR_FILTER": "", "UPLOAD_SOURCE": "", "SERVER": "", "UPLOAD_DIRECTORY": "", "UPLOAD_CONFLICT": "error", "UPLOAD_CREATE_DIRECTORY": "no"}


def validate_upload(kind, properties, *, check_source=False):
    values = {**DEFAULTS, **properties}
    if kind not in STEP_LABELS or any(not isinstance(values[key], str) or (not values[key].strip() and not (key == "JAR_FILTER" or (kind != "UPLOAD_JAR" and key == "ARTIFACT_NAME") or (kind == "UPLOAD_JAR" and key == "UPLOAD_SOURCE"))) or any(ord(char) < 32 for char in values[key]) for key in DEFAULTS):
        raise ValueError(tr("请填写有效的上传参数"))
    if values["UPLOAD_CONFLICT"] not in POLICIES or values["UPLOAD_CREATE_DIRECTORY"] not in {"yes", "no"}:
        raise ValueError(tr("请填写有效的上传参数"))
    from .jar_artifact import jar_patterns
    jar_patterns(values["JAR_FILTER"])
    if kind == "UPLOAD_JAR":
        if not values["ARTIFACT_NAME"].strip():
            raise ValueError(tr("请先添加对应的打包步骤并选择产物组"))
        return values
    source = Path(values["UPLOAD_SOURCE"]).expanduser()
    if not source.is_absolute():
        raise ValueError(tr("请选择本地文件或文件夹的完整路径"))
    # A previous build step may produce the source, so check existence only at execution.
    if check_source:
        if source.is_symlink() or getattr(source, "is_junction", lambda: False)():
            raise ValueError(tr("不支持传输链接或特殊文件：{0}", str(source)))
        if not (source.is_dir() if kind in {"UPLOAD_FOLDER", "UPLOAD_JAR"} else source.is_file()):
            raise ValueError(tr("上传来源不存在或类型不匹配：{0}", str(source)))
    values["UPLOAD_SOURCE"] = str(source)
    return values


class UploadEngine:
    def __init__(self, services, log, stop):
        self.services, self.log, self.stop = services, log, stop

    def _create_directory(self, context, directory):
        from basic.sftp.backend import open_sftp, check_cancelled
        with open_sftp(context, self.stop) as sftp:
            home = sftp.normalize(".")
            if directory == "~" or directory.startswith("~/"):
                directory = posixpath.join(home, directory[2:] if directory != "~" else "")
            directory = posixpath.normpath(posixpath.join(home, directory))
            current = "/"
            for component in directory.split("/"):
                if not component:
                    continue
                check_cancelled(context, self.stop)
                current = posixpath.join(current, component)
                try:
                    attributes = sftp.stat(current)
                except OSError as error:
                    if error.errno != errno.ENOENT:
                        raise
                    try:
                        sftp.mkdir(current)
                    except OSError:
                        # Another process may have created the directory in the meantime.
                        if not stat.S_ISDIR(sftp.stat(current).st_mode or 0):
                            raise
                    attributes = sftp.stat(current)
                if not stat.S_ISDIR(attributes.st_mode or 0):
                    raise ValueError(tr("目标不是目录：{0}", current))
            return directory

    def execute(self, kind, properties, *, artifacts=None):
        from basic.shell.context import SSHConnectionContext
        from basic.sftp.backend import transfer
        from basic.sftp.model import TransferTask, TransferCancelled
        values = validate_upload(kind, properties, check_source=True)
        if self.stop.is_set():
            raise RuntimeError(tr("执行已停止"))
        sources = (values["UPLOAD_SOURCE"],)
        if kind == "UPLOAD_JAR":
            from .jar_artifact import select_jars
            group = (artifacts or {}).get(values["ARTIFACT_NAME"])
            if not group:
                raise ValueError(tr("尚未生成可上传的产物：{0}", values["ARTIFACT_NAME"]))
            sources = tuple(str(path) for path in select_jars(group, values["JAR_FILTER"]))
            self.log(tr("使用打包产物：{0}", "\n".join(sources)))
        client = self.services.connection(values["SERVER"], self.log)
        context = SSHConnectionContext(client.get_transport(), Event())
        task = TransferTask("upload", sources, values["UPLOAD_DIRECTORY"], context, cancel=self.stop)
        last_report = 0.0

        def progress(current, total, name):
            nonlocal last_report
            now = monotonic()
            if now - last_report >= 1:
                self.log(tr("上传进度：{0}% · {1}", int(current * 100 / total) if total else 0, name))
                last_report = now

        def confirm(path):
            if values["UPLOAD_CONFLICT"] == "overwrite":
                return True
            raise FileExistsError(tr("服务器已存在同名文件：{0}", path))

        self.log(tr("开始上传：{0} → {1}", "\n".join(sources), values["UPLOAD_DIRECTORY"]))
        try:
            if values["UPLOAD_CREATE_DIRECTORY"] == "yes":
                task.destination = self._create_directory(context, task.destination)
            transfer(task, progress, confirm)
        except TransferCancelled:
            raise RuntimeError(tr("执行已停止或服务器连接已断开")) from None
        self.log(tr("上传完成：{0}", task.remote_directory))


class UploadParameterEditor(QWidget):
    changed = Signal(object)

    def __init__(self, services=None, parent=None):
        super().__init__(parent)
        self.services = services
        self.kind = None
        self._loading = False
        self.artifact_options = []
        self.artifact_results = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setVerticalSpacing(12)
        self.source = QLineEdit()
        self.source.textEdited.connect(self._changed)
        source_row = QHBoxLayout()
        source_row.addWidget(self.source, 1)
        choose = QPushButton(tr("选择"))
        choose.clicked.connect(self._choose)
        source_row.addWidget(choose)
        self.source_label = QLabel(tr("本地来源"))
        self.source_container = QWidget()
        self.source_container.setLayout(source_row)
        form.addRow(self.source_label, self.source_container)
        self.artifact = QComboBox()
        self.artifact.setView(QListView(self.artifact))
        self.artifact.setMaxVisibleItems(12)
        self.artifact.setStyleSheet("QComboBox { combobox-popup: 0; }")
        self.artifact.currentIndexChanged.connect(self._changed)
        self.artifact_label = QLabel(tr("产物名称"))
        form.addRow(self.artifact_label, self.artifact)
        self.jar_filter = QLineEdit()
        self.jar_filter.setPlaceholderText(tr("留空上传全部；多个名称或通配符用分号分隔，如 app-*.jar;lib.jar"))
        self.jar_filter.textEdited.connect(self._changed)
        self.jar_filter_label = QLabel(tr("JAR 筛选"))
        form.addRow(self.jar_filter_label, self.jar_filter)
        self.jar_preview = QLabel()
        self.jar_preview.setWordWrap(True)
        self.jar_preview.setTextFormat(Qt.TextFormat.PlainText)
        self.jar_preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow(self.jar_preview)
        self.server = QComboBox()
        server_list = QListView(self.server)
        server_list.setItemDelegate(QStyledItemDelegate(server_list))
        server_list.setUniformItemSizes(True)
        server_list.setVerticalScrollMode(QListView.ScrollMode.ScrollPerItem)
        server_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        server_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        server_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.server.setView(server_list)
        self.server.setMaxVisibleItems(12)
        self.server.setStyleSheet("QComboBox { combobox-popup: 0; } QComboBox QAbstractItemView { padding: 2px; border: 1px solid palette(mid); background: palette(base); selection-background-color: palette(highlight); selection-color: palette(highlighted-text); } QComboBox QAbstractItemView::item { min-height: 28px; padding: 2px 8px; }")
        self.server.currentIndexChanged.connect(self._changed)
        form.addRow(QLabel(tr("服务器配置")), self.server)
        self.directory = QLineEdit()
        self.directory.textEdited.connect(self._changed)
        form.addRow(QLabel(tr("服务器目录")), self.directory)
        self.create_directory = QCheckBox(str(tr("目录不存在时创建")))
        self.create_directory.toggled.connect(self._changed)
        form.addRow(self.create_directory)
        self.policy = QButtonGroup(self)
        self.policy_buttons = {}
        policies = QHBoxLayout()
        for index, (value, label) in enumerate(POLICIES.items()):
            button = QRadioButton(str(tr(label)))
            self.policy.addButton(button, index)
            self.policy_buttons[value] = button
            policies.addWidget(button)
        self.policy_buttons["error"].setChecked(True)
        self.policy.idToggled.connect(lambda _index, checked: self._changed() if checked else None)
        policies.addStretch()
        form.addRow(QLabel(tr("同名文件处理")), policies)
        layout.addLayout(form)
        self.hint = QLabel(tr("上传时保留原名称；文件夹包含自身及全部子目录。失败时停止流程，已完成的文件不会回退。"))
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        layout.addStretch()

    def display_step(self, step):
        self._loading = True
        self.kind = step["type"]
        self.source_label.setText(tr("项目目录" if self.kind == "UPLOAD_JAR" else "本地来源"))
        self.source.setPlaceholderText(tr("留空使用前面最近一次打包的项目目录") if self.kind == "UPLOAD_JAR" else "")
        self.hint.setText(tr("选择前面打包步骤的产物组；单独执行时查找该项目目录中已有的 JAR。" if self.kind == "UPLOAD_JAR" else "上传时保留原名称；文件夹包含自身及全部子目录。失败时停止流程，已完成的文件不会回退。"))
        values = {**DEFAULTS, **step.get("properties", {})}
        jar = self.kind == "UPLOAD_JAR"
        self.source_label.setVisible(not jar)
        self.source_container.setVisible(not jar)
        self.artifact_label.setVisible(jar)
        self.artifact.setVisible(jar)
        self.artifact.clear()
        selected = values["ARTIFACT_NAME"]
        if not selected:
            source = values["UPLOAD_SOURCE"]
            matches = [name for name, project in self.artifact_options if project == source] if source else []
            selected = matches[-1] if matches else self.artifact_options[-1][0] if self.artifact_options and not source else ""
        self.artifact.addItem(str(tr("请选择产物组")), "")
        for name, _project in self.artifact_options:
            self.artifact.addItem(name, name)
        if selected and self.artifact.findData(selected) < 0:
            self.artifact.addItem(selected, selected)
        self.artifact.setCurrentIndex(max(0, self.artifact.findData(selected)))
        self.source.setText(values["UPLOAD_SOURCE"])
        self.jar_filter.setText(values["JAR_FILTER"])
        for widget in (self.jar_filter_label, self.jar_filter, self.jar_preview):
            widget.setVisible(self.kind == "UPLOAD_JAR")
        self.directory.setText(values["UPLOAD_DIRECTORY"])
        self.create_directory.setChecked(values["UPLOAD_CREATE_DIRECTORY"] == "yes")
        self.server.clear()
        self.server.addItem(str(tr("请选择服务器")), "")
        names = self.services.store.list_names() if self.services else []
        if values["SERVER"] and values["SERVER"] not in names:
            names.append(values["SERVER"])
        for name in names:
            self.server.addItem(name, name)
        self.server.setCurrentIndex(max(0, self.server.findData(values["SERVER"])))
        self.policy_buttons.get(values["UPLOAD_CONFLICT"], self.policy_buttons["error"]).setChecked(True)
        self._loading = False
        self.refresh_jars()

    def values(self):
        return {"ARTIFACT_NAME": (self.artifact.currentData() or "") if self.kind == "UPLOAD_JAR" else "", "JAR_FILTER": self.jar_filter.text().strip() if self.kind == "UPLOAD_JAR" else "", "UPLOAD_SOURCE": self.source.text().strip(), "SERVER": self.server.currentData() or "", "UPLOAD_DIRECTORY": self.directory.text().strip(), "UPLOAD_CREATE_DIRECTORY": "yes" if self.create_directory.isChecked() else "no", "UPLOAD_CONFLICT": next(value for value, button in self.policy_buttons.items() if button.isChecked())}

    def _changed(self, *_args):
        if not self._loading and self.kind:
            self.changed.emit(self.values())
            self.refresh_jars()

    def refresh_jars(self):
        if self.kind != "UPLOAD_JAR":
            return
        group = self.artifact_results.get(self.artifact.currentData())
        if not group:
            self.jar_preview.setText(tr("单独执行时检查本地 JAR；完整流程使用本次打包产物。"))
            return
        from .jar_artifact import select_jars
        try:
            files = select_jars(group, self.jar_filter.text())
            self.jar_preview.setText(tr("已识别 {0} 个 JAR：{1}", len(files), "\n".join(str(path) for path in files)))
        except (OSError, ValueError) as error:
            self.jar_preview.setText(str(error))

    def _choose(self):
        if self.kind in {"UPLOAD_FOLDER", "UPLOAD_JAR"}:
            path = choose_directory(self, tr("选择目录"), self.source.text())
        else:
            path, _ = choose_file(self, tr(STEP_LABELS[self.kind]), self.source.text(), "*.jar" if self.kind == "UPLOAD_JAR" else "*")
        if path:
            self.source.setText(path)
            self._changed()



class UploadDialog(QDialog):
    def __init__(self, services, kind, properties=None, parent=None, artifact_options=(), artifact_results=None):
        super().__init__(parent)
        self.setWindowTitle(tr(STEP_LABELS[kind]))
        self.resize(700, 500)
        layout = parameter_dialog_layout(self, tr(STEP_LABELS[kind]))
        self.editor = UploadParameterEditor(services, self)
        self.editor.artifact_options = list(artifact_options)
        self.editor.artifact_results = artifact_results or {}
        self.editor.display_step({"type": kind, "properties": properties or {}})
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
            validate_upload(self.editor.kind, self.properties())
        except ValueError as error:
            QMessageBox.warning(self, tr("文件上传"), str(error))
            return
        self.accept()
