"""Keep native tab sorting and start a panel drag outside the tab strip."""

from PySide6.QtCore import QEvent, QMimeData, Qt
from PySide6.QtGui import QDrag, QMouseEvent
from PySide6.QtWidgets import QApplication, QTabBar
from shiboken6 import isValid


PANEL_MIME = "application/x-pipeterminal-panel"


class PanelTabBar(QTabBar):
    def __init__(self, group):
        super().__init__(group)
        self.group = group
        self.dragged_panel = None
        self._pressed_panel = None
        self._press_position = None

    def mousePressEvent(self, event):
        self._pressed_panel = None
        self._press_position = None
        index = self.tabAt(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and index >= 0 and self.isTabEnabled(index):
            self._pressed_panel = self.group.widget(index)
            self._press_position = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        point = event.position().toPoint()
        if (self._pressed_panel is not None and event.buttons() & Qt.MouseButton.LeftButton
                and not self.rect().contains(point)
                and (point - self._press_position).manhattanLength() >= QApplication.startDragDistance()):
            panel = self._pressed_panel
            self._pressed_panel = None
            # Finish QTabBar's internal sorting gesture before entering QDrag.
            release = QMouseEvent(QEvent.Type.MouseButtonRelease, event.position(), event.globalPosition(),
                                  Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, event.modifiers())
            super().mouseReleaseEvent(release)
            self.dragged_panel = panel
            drag = QDrag(self)
            mime = QMimeData()
            mime.setData(PANEL_MIME, b"panel")
            drag.setMimeData(mime)
            index = self.group.indexOf(panel)
            if index >= 0:
                drag.setPixmap(self.grab(self.tabRect(index)))
            try:
                drag.exec(Qt.DropAction.MoveAction)
            finally:
                self.dragged_panel = None
                if isValid(drag):
                    drag.deleteLater()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._pressed_panel = None
        self._press_position = None
        super().mouseReleaseEvent(event)
