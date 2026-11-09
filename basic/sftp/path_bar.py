"""Breadcrumb navigation, editable addresses and path copying."""

from pathlib import PurePosixPath

from PySide6.QtCore import QEvent, QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QHBoxLayout, QScrollArea,
    QSizePolicy, QStackedWidget, QToolButton, QWidget,
)

from common.i18n import tr
from common.i18n.widgets import QLineEdit, QPushButton
from common.qt.icons import create_icon

from .file_icons import RemoteFileIcons
from .path_menu import PathDirectoryMenu


class RemotePathBar(QWidget):
    path_requested = Signal(str)

    def __init__(self, parent=None, *, path_type=PurePosixPath, directory_menu_factory=PathDirectoryMenu) -> None:
        super().__init__(parent)
        self._path_type = path_type
        self._directory = ""
        self._history = []
        self._request_pending = False
        self._requested_path = ""
        self._editing = True
        self._outside_filter_installed = False
        self._last_segment = None
        self._folder_icon = RemoteFileIcons().folder_icon()
        self._directory_menu = directory_menu_factory(self)
        self._directory_menu.path_selected.connect(self._queue_request)
        path_font = self.font()
        path_font.setPointSize(10)
        self.setFont(path_font)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.address = QComboBox(self)
        self.address.setObjectName("remotePathAddress")
        self.address.setEditable(True)
        self.address.setLineEdit(QLineEdit())
        self.address.lineEdit().setObjectName("remotePathEditor")
        self.address.lineEdit().setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.address.lineEdit().setTextMargins(0, 0, 0, 0)
        self.address.setStyleSheet(
            "QComboBox#remotePathAddress { padding:0 26px 0 8px; min-height:0; }"
            "QComboBox#remotePathAddress QLineEdit#remotePathEditor {"
            " padding:0; border:0; min-height:0; background:transparent; }"
        )
        self.address.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.address.setCompleter(None)
        self.address.setMaxVisibleItems(12)
        self.address.setMinimumContentsLength(1)
        self.address.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.address.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.address.lineEdit().setPlaceholderText(tr("输入路径后按 Enter 跳转"))
        self.address.lineEdit().returnPressed.connect(lambda: self._queue_request(self.text()))
        self.address.activated.connect(self._choose_path)
        self.stack = QStackedWidget(self)
        self.stack.setMinimumWidth(0)
        self.stack.addWidget(self.address)
        self.breadcrumb_scroll = QScrollArea(self)
        self.breadcrumb_scroll.setObjectName("remoteBreadcrumbBar")
        self.breadcrumb_scroll.setWidgetResizable(True)
        self.breadcrumb_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.breadcrumb_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.breadcrumb_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.breadcrumb_scroll.setStyleSheet(
            "QScrollArea#remoteBreadcrumbBar { background:palette(base); border:1px solid palette(mid); border-radius:5px; }"
            "QWidget#remoteBreadcrumbContent { background:transparent; }"
            "QToolButton { background:transparent; border:0; padding:0 6px; min-height:22px; border-radius:3px; }"
            "QToolButton:hover { background:palette(highlight); color:palette(highlighted-text); }"
        )
        self.crumbs = QWidget()
        self.crumbs.setObjectName("remoteBreadcrumbContent")
        self.crumbs.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        self.crumb_layout = QHBoxLayout(self.crumbs)
        self.crumb_layout.setContentsMargins(4, 1, 24, 1)
        self.crumb_layout.setSpacing(0)
        self.breadcrumb_scroll.setWidget(self.crumbs)
        self.stack.addWidget(self.breadcrumb_scroll)
        layout.addWidget(self.stack, 1)
        self.history_button = QPushButton("▾")
        self.history_button.setFixedWidth(26)
        self.history_button.setStyleSheet("padding:0; min-height:0;")
        self.history_button.setToolTip(tr("最近访问路径"))
        self.history_button.clicked.connect(self._show_history)
        self.history_button.hide()
        layout.addWidget(self.history_button)
        self.copy_button = QPushButton()
        self.copy_button.setFixedWidth(32)
        self.copy_button.setStyleSheet("padding:0; min-height:0;")
        self.copy_button.setIcon(create_icon("copy"))
        self.copy_button.setToolTip(tr("复制路径"))
        self.copy_button.clicked.connect(self._copy_path)
        self.copy_button.setEnabled(False)
        self.address.editTextChanged.connect(lambda text: self.copy_button.setEnabled(bool(text)))
        layout.addWidget(self.copy_button)
        self.setFocusProxy(self.address.lineEdit())
        self.crumbs.installEventFilter(self)
        self.breadcrumb_scroll.viewport().installEventFilter(self)
        self._sync_height()

    def bind_session(self, session) -> None:
        self._directory_menu.bind_session(session)

    def text(self) -> str:
        return self.address.currentText()

    def setText(self, text: str) -> None:
        self.address.setEditText(text)

    def record_path(self, directory: str) -> None:
        changed = directory != self._directory
        self._directory = directory
        self._history = [directory, *(path for path in self._history if path != directory)][:30]
        self.setText(directory)
        self._rebuild_choices()
        if changed or self._last_segment is None:
            self._rebuild_breadcrumbs()
        self._show_breadcrumbs()

    def reset_history(self) -> None:
        self._stop_outside_filter()
        self._history.clear()
        self._directory = ""
        self._request_pending = False
        self._requested_path = ""
        self._directory_menu.close()
        self._rebuild_choices()
        self._rebuild_breadcrumbs()
        self._editing = True
        self.stack.setCurrentWidget(self.address)
        self.history_button.hide()

    def _rebuild_breadcrumbs(self) -> None:
        self._directory_menu.close()
        while self.crumb_layout.count():
            item = self.crumb_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self._last_segment = None
        parts = []
        directory = self._path_type(self._directory)
        if self._directory and directory.is_absolute():
            path = self._path_type(directory.anchor)
            parts.append((directory.anchor, str(path)))
            for name in directory.parts[1:]:
                path = path / name
                parts.append((name, str(path)))
        elif self._directory:
            parts.append((self._directory, self._directory))
        for index, (name, path) in enumerate(parts):
            button = QToolButton(self.crumbs)
            button.setText(name.replace("&", "&&"))
            button.setToolTip(path)
            if index == 0:
                button.setIcon(self._folder_icon)
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.clicked.connect(lambda _checked=False, value=path: self._queue_request(value))
            self.crumb_layout.addWidget(button)
            arrow = QToolButton(self.crumbs)
            arrow.setText("›")
            arrow.setFixedWidth(20)
            arrow.setToolTip(path)
            arrow.clicked.connect(lambda _checked=False, value=path, anchor=arrow: self._directory_menu.show(value, anchor))
            self.crumb_layout.addWidget(arrow)
            self._last_segment = arrow
        self.crumb_layout.addStretch(1)
        QTimer.singleShot(0, self._scroll_to_current)

    def _scroll_to_current(self) -> None:
        if self._last_segment is not None:
            self.breadcrumb_scroll.ensureWidgetVisible(self._last_segment, 0, 0)
            scrollbar = self.breadcrumb_scroll.horizontalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _begin_edit(self) -> None:
        self._directory_menu.close()
        self._editing = True
        self.stack.setCurrentWidget(self.address)
        self.history_button.hide()
        if not self._outside_filter_installed:
            QApplication.instance().installEventFilter(self)
            self._outside_filter_installed = True
        self.address.lineEdit().setFocus()
        self.address.lineEdit().selectAll()

    def _show_breadcrumbs(self) -> None:
        if not self._directory:
            return
        self._stop_outside_filter()
        self.address.hidePopup()
        self._editing = False
        self.setText(self._directory)
        self.stack.setCurrentWidget(self.breadcrumb_scroll)
        self.history_button.show()
        QTimer.singleShot(0, self._scroll_to_current)

    def _finish_edit(self) -> None:
        if self._editing and not self.address.view().isVisible() and not (
            self.address.hasFocus() or self.address.lineEdit().hasFocus()
        ):
            self._show_breadcrumbs()

    def _show_history(self) -> None:
        self._begin_edit()
        self.address.showPopup()

    def close_popups(self) -> None:
        self._request_pending = False
        self._directory_menu.close()
        self._show_breadcrumbs()

    def _stop_outside_filter(self) -> None:
        if self._outside_filter_installed:
            QApplication.instance().removeEventFilter(self)
            self._outside_filter_installed = False

    def _sync_height(self) -> None:
        height = max(30, self.fontMetrics().height() + 12)
        self.stack.setFixedHeight(height)
        self.address.setFixedHeight(height)
        self.history_button.setFixedHeight(height)
        self.copy_button.setFixedHeight(height)

    def eventFilter(self, watched, event) -> bool:
        if self._editing and self._directory and event.type() == QEvent.Type.MouseButtonPress and isinstance(watched, QWidget):
            popup = self.address.view().window()
            inside = (
                watched is self or self.isAncestorOf(watched)
                or watched is popup or popup.isAncestorOf(watched)
            )
            if not inside:
                self._show_breadcrumbs()
        if watched in (self.crumbs, self.breadcrumb_scroll.viewport()):
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._begin_edit()
                return True
        elif watched in (self.address, self.address.lineEdit()):
            if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape and self._directory:
                self._show_breadcrumbs()
                return True
            if event.type() == QEvent.Type.FocusOut:
                QTimer.singleShot(0, self._finish_edit)
        return super().eventFilter(watched, event)

    def _rebuild_choices(self) -> None:
        text = self.text()
        parents = []
        directory = self._path_type(self._directory)
        if self._directory and directory.is_absolute():
            parents = [str(directory), *(str(parent) for parent in directory.parents)]
        recent = [path for path in self._history if path not in parents]
        blocker = QSignalBlocker(self.address)
        self.address.clear()
        for path in parents:
            self.address.addItem(path, path)
            self.address.setItemData(self.address.count() - 1, path, Qt.ItemDataRole.ToolTipRole)
        if parents and recent:
            self.address.insertSeparator(self.address.count())
        for path in recent:
            self.address.addItem(path, path)
            self.address.setItemData(self.address.count() - 1, path, Qt.ItemDataRole.ToolTipRole)
        self.address.setCurrentIndex(-1)
        self.address.setEditText(text)
        del blocker
        self.copy_button.setEnabled(bool(text))

    def _choose_path(self, index: int) -> None:
        path = self.address.itemData(index)
        if isinstance(path, str):
            self._queue_request(path)

    def _queue_request(self, path: str) -> None:
        self._requested_path = path
        if not self._request_pending:
            self._request_pending = True
            QTimer.singleShot(0, self._send_request)

    def _send_request(self) -> None:
        if not self._request_pending:
            return
        self._request_pending = False
        if self.isEnabled():
            self.path_requested.emit(self._requested_path)

    def _copy_path(self) -> None:
        QApplication.clipboard().setText(self.text())

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in {QEvent.Type.PaletteChange, QEvent.Type.StyleChange} and hasattr(self, "copy_button"):
            self.copy_button.setIcon(create_icon("copy"))
        if event.type() in {QEvent.Type.FontChange, QEvent.Type.StyleChange} and hasattr(self, "copy_button"):
            self._sync_height()

    def hideEvent(self, event) -> None:
        self._stop_outside_filter()
        self._show_breadcrumbs()
        self._directory_menu.close()
        super().hideEvent(event)

    def shutdown(self) -> None:
        self._stop_outside_filter()
        self._request_pending = False
        self._directory_menu.shutdown()
