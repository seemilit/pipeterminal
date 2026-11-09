"""Remote editing stays responsive while a separate worker reads or saves."""

from pathlib import Path
from threading import Thread

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QMessageBox, QVBoxLayout

from common.i18n import tr
from common.i18n.widgets import QAction, QDialog, QLabel, QPlainTextEdit, QPushButton
from ..file_operations.controller import FileOperationController
from . import backend

from common.i18n.errors import error_message


class RemoteFileEditor(QDialog):
    directory_changed = Signal(object)
    _local_saved = Signal(str)

    def __init__(self, session, context, path, parent=None, log_service=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(tr("远程文件编辑：{0}", path))
        self.resize(820, 560)
        self.context, self.path = context, path
        self._document = None
        self._close_after_save = False
        self._force_closing = False
        self._local_busy = False
        self._local_saved.connect(self._local_result, Qt.ConnectionType.QueuedConnection)
        self.controller = FileOperationController(self)
        self.controller.bind_session(session, path, log_service)
        self.controller.completed.connect(self._completed)
        self.controller.directories_changed.connect(self.directory_changed.emit)
        self.controller.busy_changed.connect(self._busy_changed)
        layout = QVBoxLayout(self)
        self.editor = QPlainTextEdit()
        self.editor.setReadOnly(True)
        layout.addWidget(self.editor, 1)
        row = QHBoxLayout()
        self.status = QLabel(tr("正在读取文件…"))
        row.addWidget(self.status, 1)
        self.save_button = QPushButton(tr("保存"))
        self.save_button.clicked.connect(self.save)
        self.local_button = QPushButton(tr("另存本地"))
        self.local_button.clicked.connect(self._save_local)
        close = QPushButton(tr("关闭"))
        close.clicked.connect(self.close)
        for button in (self.save_button, self.local_button, close):
            row.addWidget(button)
        layout.addLayout(row)
        action = QAction(tr("保存"), self)
        action.setShortcut(QKeySequence.StandardKey.Save)
        action.triggered.connect(self.save)
        self.addAction(action)
        self._busy_changed(True)
        self._start("load", lambda ctx, cancel, result, progress: backend.load(ctx, cancel, result, progress, path))

    def _start(self, owner, work, affected=()):
        job = self.controller.start(tr("读取文件" if owner == "load" else "保存文件"), self.context, work,
                                    owner=owner, affected=affected, paths=(self.path,))
        if job is None:
            self.status.setText(tr("连接已改变，操作结果已丢弃"))
            self._busy_changed(False)
        return job

    def _busy_changed(self, busy):
        loaded = self._document is not None
        self.editor.setReadOnly(busy or not loaded)
        self.save_button.setEnabled(not busy and loaded)
        self.local_button.setEnabled(not busy and loaded)

    def _completed(self, job, error):
        if error:
            self._close_after_save = False
            self.status.setText(tr("操作失败：{0}", error))
            QMessageBox.warning(self, tr("远程文件编辑"), tr("操作失败：{0}", error))
            return
        self._document = job.result["document"]
        if job.owner == "load":
            self.path = self._document.path
            self.setWindowTitle(tr("远程文件编辑：{0}", self.path))
            self.editor.setPlainText(self._document.text)
        self.editor.document().setModified(False)
        self._busy_changed(False)
        self.status.setText(tr("文件已载入" if job.owner == "load" else "保存成功"))
        if self._close_after_save:
            self._close_after_save = False
            self.close()

    def save(self):
        if self.controller.busy or self._local_busy or self._document is None or not self.editor.document().isModified():
            return
        try:
            data = backend.encode_document(self._document, self.editor.toPlainText())
        except (ValueError, UnicodeError) as exc:
            self._close_after_save = False
            QMessageBox.warning(self, tr("保存失败"), error_message(exc))
            return
        self.status.setText(tr("正在保存…"))
        document = self._document
        if self._start("save", lambda ctx, cancel, result, progress: backend.save(ctx, cancel, result, progress, document, data)) is None:
            self._close_after_save = False

    def _save_local(self):
        if self._document is None or self.controller.busy or self._local_busy:
            return
        filename, _filter = QFileDialog.getSaveFileName(self, tr("另存本地"), Path(self.path).name)
        if filename:
            try:
                data = backend.encode_document(self._document, self.editor.toPlainText())
            except (ValueError, UnicodeError) as exc:
                QMessageBox.warning(self, tr("保存失败"), error_message(exc))
                return
            self._local_busy = True
            self._busy_changed(True)
            self.status.setText(tr("正在保存…"))
            Thread(target=self._write_local, args=(filename, data), name="file-edit-local-save", daemon=True).start()

    def _write_local(self, filename, data):
        try:
            Path(filename).write_bytes(data)
            error = ""
        except OSError as exc:
            error = error_message(exc)
        try:
            self._local_saved.emit(error)
        except RuntimeError:
            pass

    def _local_result(self, error):
        self._local_busy = False
        self._busy_changed(False)
        self.status.setText(tr("操作失败：{0}", error) if error else tr("已另存本地"))
        if error:
            QMessageBox.warning(self, tr("保存失败"), str(error))

    def closeEvent(self, event):
        if self._force_closing:
            super().closeEvent(event)
            return
        if self._local_busy:
            event.ignore()
            return
        if self.controller.busy:
            if self._document is None:
                self.controller.shutdown()
                super().closeEvent(event)
                return
            self.controller.cancel()
            self.status.setText(tr("正在取消操作，请稍后关闭"))
            event.ignore()
            return
        if self.editor.document().isModified():
            self.show()
            self.raise_()
            answer = QMessageBox.question(self, tr("存在未保存内容"), tr("是否先保存当前文件？"),
                                         QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                         QMessageBox.StandardButton.Cancel)
            if answer == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if answer == QMessageBox.StandardButton.Save:
                self._close_after_save = True
                self.save()
                event.ignore()
                return
        self.controller.shutdown()
        super().closeEvent(event)

    def shutdown(self):
        self._force_closing = True
        self.controller.shutdown()
        self.editor.document().setModified(False)
        self.close()
