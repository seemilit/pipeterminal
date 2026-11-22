"""Scoped, searchable log lists with background catalog loading."""

from threading import Thread

from PySide6.QtCore import QSignalBlocker, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QListWidget, QListWidgetItem, QMessageBox, QSplitter, QVBoxLayout

from common.i18n import tr
from common.i18n.errors import error_message
from common.i18n.widgets import QComboBox, QDialog, QLabel, QPushButton

from .page import LogPage


class LogBrowserDialog(QDialog):
    catalog_loaded = Signal(int, object, str)

    def __init__(self, title, service, sources, parent=None, *, show_folder=False, deletions=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(980, 620)
        self._sources = sources
        self._deletions = deletions or {}
        self._request = 0
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.category = QComboBox()
        for label in sources:
            self.category.addItem(tr(label), label)
        toolbar.addWidget(self.category)
        toolbar.addStretch(1)
        if show_folder:
            folder = QPushButton(tr("打开日志目录"))
            folder.clicked.connect(self._open_folder)
            toolbar.addWidget(folder)
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.files = QListWidget()
        splitter.addWidget(self.files)
        self.viewer = LogPage(external_directory=True)
        self.viewer.bind_service(service, read_log=self._read_log)
        self.viewer.refresh_button.clicked.connect(self._refresh_catalog)
        splitter.addWidget(self.viewer)
        splitter.setSizes([280, 700])
        layout.addWidget(splitter, 1)

        footer = QHBoxLayout()
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        footer.addWidget(self.notice, 1)
        self.delete_button = QPushButton(tr("删除"))
        self.delete_button.setEnabled(False)
        self.delete_button.setVisible(bool(self._deletions))
        self.delete_button.clicked.connect(self._delete_log)
        footer.addWidget(self.delete_button)
        close = QPushButton(tr("关闭"))
        close.clicked.connect(self.reject)
        footer.addWidget(close)
        layout.addLayout(footer)

        self.files.currentItemChanged.connect(self._select)
        self.category.currentIndexChanged.connect(self._change_category)
        self.catalog_loaded.connect(self._display_catalog, Qt.ConnectionType.QueuedConnection)
        self.viewer.activate()
        self.finished.connect(lambda _result: self.viewer._timer.stop())
        self._refresh_catalog()

    def _change_category(self):
        self.files.clear()
        self._select(None)
        self._refresh_catalog()

    def _refresh_catalog(self):
        self._request += 1
        request = self._request
        catalog, _, _ = self._sources[self.category.currentData()]
        self.notice.setText(tr("正在读取日志列表…"))
        Thread(target=self._load_catalog, args=(request, catalog), name="log-catalog", daemon=True).start()

    def _load_catalog(self, request, catalog):
        try:
            rows, error = catalog(), ""
        except (OSError, ValueError) as exc:
            rows, error = [], error_message(exc)
        try:
            self.catalog_loaded.emit(request, rows, error)
        except RuntimeError:
            pass

    def _display_catalog(self, request, rows, error):
        if request != self._request:
            return
        current = self.files.currentItem()
        identifier = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        selected = None
        with QSignalBlocker(self.files):
            self.files.clear()
            for path, label in rows:
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, path)
                self.files.addItem(item)
                if path == identifier:
                    selected = item
            self.files.setCurrentItem(selected if selected is not None else self.files.item(0))
        self._select(self.files.currentItem())
        self.notice.setText(error or ("" if rows else tr("暂无日志")))

    def _select(self, item, _previous=None):
        identifier = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        key = f"{self.category.currentIndex()}/{identifier}" if identifier is not None else None
        self.viewer.select_item(key)
        self.delete_button.setEnabled(
            identifier is not None and self.category.currentData() in self._deletions
        )

    def _delete_log(self):
        item = self.files.currentItem()
        operation = self._deletions.get(self.category.currentData())
        if item is None or operation is None:
            return
        delete, is_active = operation
        identifier = item.data(Qt.ItemDataRole.UserRole)
        try:
            if is_active is not None and is_active(identifier):
                self.notice.setText(tr("日志正在写入，暂时无法删除"))
                return
        except (OSError, ValueError) as exc:
            self.notice.setText(error_message(exc))
            return
        if QMessageBox.question(
            self, tr("删除"), tr("确定删除日志“{0}”吗？", item.text()),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            if is_active is not None and is_active(identifier):
                self.notice.setText(tr("日志正在写入，暂时无法删除"))
                return
            delete(identifier)
        except (OSError, ValueError) as exc:
            self.notice.setText(error_message(exc))
        else:
            self._refresh_catalog()

    def _read_log(self, key):
        index, path = key.split("/", 1)
        _, reader, _ = tuple(self._sources.values())[int(index)]
        return reader(path)

    def _open_folder(self):
        _, _, folder = self._sources[self.category.currentData()]
        try:
            folder.mkdir(parents=True, exist_ok=True)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
                raise OSError(tr("无法打开日志目录"))
        except OSError as exc:
            QMessageBox.warning(self, tr("诊断"), error_message(exc))
