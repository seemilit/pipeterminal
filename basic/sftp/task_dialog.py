"""Fixed-size transfer-list window without file browsing or directory reads."""

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QVBoxLayout

from common.i18n import tr
from common.i18n.widgets import QDialog, QLabel, QPushButton
from common.qt.icons import create_icon

from .task_cards import TransferTaskCards


class TransferTasksDialog(QDialog):
    remote_location_requested = Signal(object)

    def __init__(self, controller, parent=None, *, anchor=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("传输列表"))
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setFixedSize(360, 330)
        self._anchor = anchor
        self._position_pending = False
        self._closed = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        panel = QFrame(self)
        panel.setObjectName("transferTasksWindow")
        panel.setStyleSheet(
            "QFrame#transferTasksWindow { background:palette(window); color:palette(window-text); "
            "border:1px solid palette(mid); border-radius:4px; }"
            "QFrame#transferTaskCard { border:0; border-bottom:1px solid palette(mid); }"
            "QLabel { border:0; }"
            "QPushButton { padding:0 4px; min-height:20px; max-height:20px; border-radius:2px; }"
            "QProgressBar { min-height:14px; max-height:14px; }"
        )
        root = QVBoxLayout(panel)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        heading = QHBoxLayout()
        heading.setContentsMargins(10, 6, 6, 6)
        heading.setSpacing(4)
        self.title = QLabel()
        font = self.title.font()
        font.setBold(True)
        self.title.setFont(font)
        heading.addWidget(self.title, 1)
        cancel_all = QPushButton(tr("取消全部任务"))
        cancel_all.setFixedHeight(22)
        cancel_all.clicked.connect(controller.cancel_all)
        heading.addWidget(cancel_all)
        clear = QPushButton()
        self.clear_button = clear
        clear.setIcon(create_icon("delete"))
        clear.setFixedSize(26, 22)
        clear.setToolTip(tr("清除已结束任务"))
        clear.clicked.connect(controller.clear_finished)
        heading.addWidget(clear)
        hide = QPushButton("—")
        hide.setFixedSize(26, 22)
        hide.setToolTip(tr("隐藏传输列表"))
        hide.clicked.connect(self.hide)
        heading.addWidget(hide)
        root.addLayout(heading)
        self.task_list = TransferTaskCards(controller, panel)
        self.task_list.count_changed.connect(self._update_title)
        self.task_list.remote_location_requested.connect(self.remote_location_requested.emit)
        self._update_title(self.task_list.count)
        root.addWidget(self.task_list, 1)
        layout.addWidget(panel)
        if anchor is not None:
            anchor.installEventFilter(self)
        if parent is not None:
            parent.installEventFilter(self)

    def _update_title(self, count: int) -> None:
        self.title.setText(tr("传输列表（{0}）", count))

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in {QEvent.Type.PaletteChange, QEvent.Type.StyleChange} and hasattr(self, "clear_button"):
            self.clear_button.setIcon(create_icon("delete"))

    def _position_near_anchor(self) -> None:
        self._position_pending = False
        if self._closed or self._anchor is None or not self._anchor.isVisible():
            return
        point = self._anchor.mapToGlobal(QPoint(self._anchor.width(), self._anchor.height() + 6))
        screen = self._anchor.screen()
        if screen is None:
            return
        area = screen.availableGeometry()
        x = max(area.left(), min(point.x() - self.width(), area.right() + 1 - self.width()))
        y = point.y()
        if y + self.height() > area.bottom() + 1:
            y = self._anchor.mapToGlobal(QPoint(0, -self.height() - 6)).y()
        y = max(area.top(), min(y, area.bottom() + 1 - self.height()))
        self.move(x, y)

    def eventFilter(self, watched, event) -> bool:
        if self.isVisible() and not self._closed:
            if event.type() == QEvent.Type.MouseButtonPress:
                point = event.globalPosition().toPoint()
                popup = QApplication.activePopupWidget()
                inside_popup = popup is not None and self.isAncestorOf(popup) and popup.frameGeometry().contains(point)
                inside_anchor = self._anchor is not None and self._anchor.rect().contains(self._anchor.mapFromGlobal(point))
                if not self.frameGeometry().contains(point) and not inside_popup and not inside_anchor:
                    self.hide()
            elif event.type() == QEvent.Type.ApplicationDeactivate:
                self.hide()
            elif watched is self and event.type() == QEvent.Type.WindowDeactivate:
                QTimer.singleShot(0, self._hide_if_inactive)
        if watched in (self._anchor, self.parentWidget()) and self.isVisible() and not self._closed and not self._position_pending and event.type() in {QEvent.Type.Move, QEvent.Type.Resize}:
            self._position_pending = True
            QTimer.singleShot(0, self._position_near_anchor)
        return super().eventFilter(watched, event)

    def _hide_if_inactive(self) -> None:
        if self._closed:
            return
        popup = QApplication.activePopupWidget()
        if self.isVisible() and not self.isActiveWindow() and not (popup is not None and self.isAncestorOf(popup)):
            self.hide()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QApplication.instance().installEventFilter(self)

    def hideEvent(self, event) -> None:
        QApplication.instance().removeEventFilter(self)
        super().hideEvent(event)

    def show_tasks(self) -> None:
        if self.isVisible():
            self.hide()
            return
        self.show()
        self._position_near_anchor()
        self.raise_()
        self.activateWindow()

    def shutdown(self) -> None:
        self._closed = True
        QApplication.instance().removeEventFilter(self)
        if self._anchor is not None:
            self._anchor.removeEventFilter(self)
        if self.parentWidget() is not None:
            self.parentWidget().removeEventFilter(self)
        self.task_list.shutdown()
        self.close()
