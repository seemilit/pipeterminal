"""One saved access directory and its optional default command."""

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout

from common.i18n import tr
from common.i18n.widgets import QLabel, QLineEdit, QPushButton
from common.qt.checkbox import SquareCheckBox

from .model import AccessPath


class AccessPathRow(QFrame):
    changed = Signal()
    default_selected = Signal(object)
    remove_requested = Signal(object)
    connect_requested = Signal(object)
    row_selected = Signal(object)

    def __init__(self, index: int, value: AccessPath) -> None:
        super().__init__()
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setObjectName("serverAccessPathRow")
        self.setProperty("active", False)
        self._pending_action: str | None = None
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._click_timer.timeout.connect(self._run_pending_action)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 5, 6, 5)
        layout.setSpacing(6)
        self.position_label = QLabel(tr("位置 {0}", index))
        layout.addWidget(self.position_label)
        self.selected = SquareCheckBox(tr("默认路径"))
        self.selected.setObjectName("pathOption")
        self.selected.setChecked(value.selected)
        layout.addWidget(self.selected)
        self.command_enabled = SquareCheckBox(tr("执行命令"))
        self.command_enabled.setObjectName("pathOption")
        self.command_enabled.setChecked(value.command_enabled and bool(value.command.strip()))
        self.command_enabled.setEnabled(bool(value.command.strip()))
        layout.addWidget(self.command_enabled)
        self.path = QLineEdit(value.path)
        self.path.setPlaceholderText(tr("服务器目录"))
        layout.addWidget(self.path, 1)
        self.command = QLineEdit(value.command)
        self.command.setPlaceholderText(tr("进入目录后自动执行的命令，可留空"))
        layout.addSpacing(8)
        layout.addWidget(self.command, 1)
        self.connect_button = QPushButton(tr("直接连接"))
        self.connect_button.setEnabled(bool(value.path.strip()))
        self.connect_button.clicked.connect(lambda _checked=False: self._queue_action("connect"))
        layout.addWidget(self.connect_button)
        self.remove_button = QPushButton(tr("删除"))
        self.remove_button.clicked.connect(self._remove)
        layout.addWidget(self.remove_button)
        self.path.textChanged.connect(self._path_changed)
        self.command.textChanged.connect(self._command_changed)
        self.selected.toggled.connect(self._default_changed)
        self.command_enabled.toggled.connect(self.changed)
        for target in (
            self, self.position_label, self.selected, self.command_enabled,
            self.path, self.command, self.connect_button, self.remove_button,
        ):
            target.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.FocusIn or (
            event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton
        ):
            self.row_selected.emit(self)
        if (
            event.type() == QEvent.Type.MouseButtonDblClick
            and event.button() == Qt.MouseButton.LeftButton
            and watched is not self.remove_button
        ):
            self._click_timer.stop()
            self._pending_action = None
            self.row_selected.emit(self)
            if self.connect_button.isEnabled():
                self.connect_requested.emit(self)
            return True
        return super().eventFilter(watched, event)

    def _queue_action(self, action: str) -> None:
        self._pending_action = action
        self._click_timer.start(QApplication.doubleClickInterval())

    def _run_pending_action(self) -> None:
        action, self._pending_action = self._pending_action, None
        if action == "connect" and self.connect_button.isEnabled():
            self.connect_requested.emit(self)

    def _remove(self) -> None:
        self._click_timer.stop()
        self._pending_action = None
        self.remove_requested.emit(self)

    def value(self) -> AccessPath:
        return AccessPath(
            self.path.text().strip(), self.command.text().strip(),
            self.selected.isChecked(), self.command_enabled.isChecked(),
        )

    def _default_changed(self, checked: bool) -> None:
        if checked:
            self.default_selected.emit(self)
        self.changed.emit()

    def _path_changed(self, value: str) -> None:
        self.connect_button.setEnabled(bool(value.strip()))
        self.changed.emit()

    def _command_changed(self, value: str) -> None:
        enabled = bool(value.strip())
        if not enabled:
            self.command_enabled.setChecked(False)
        self.command_enabled.setEnabled(enabled)
        self.changed.emit()
