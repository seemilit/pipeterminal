"""One independently selectable group of application panel tabs."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTabBar, QToolButton, QWidget

from common.i18n import tr
from common.i18n.widgets import QTabWidget

from .module_page import ModulePage
from .panel_tab_bar import PanelTabBar
from .tab_scroll_style import PanelTabScrollStyle


class PanelTabGroup(QTabWidget):
    activated = Signal()
    new_panel_requested = Signal(object)
    context_menu_requested = Signal(object, object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setTabBar(PanelTabBar(self))
        self.setObjectName("bottomPanelTabs")
        self.setMinimumWidth(220)
        self.setUsesScrollButtons(True)
        self.setMovable(True)
        self.setElideMode(Qt.TextElideMode.ElideNone)
        self.tabBar().setExpanding(False)
        self._tab_scroll_style = PanelTabScrollStyle(self.tabBar())
        self.tabBar().setStyle(self._tab_scroll_style)
        self._new_panel_tab = QWidget()
        self.addTab(self._new_panel_tab, "")
        self.setTabEnabled(0, False)
        self.setTabToolTip(0, tr("新建"))
        self._new_panel_button = QToolButton(self.tabBar())
        self._new_panel_button.setObjectName("panelAddButton")
        self._new_panel_button.setText("+")
        self._new_panel_button.setAutoRaise(True)
        self._new_panel_button.setFixedSize(26, 26)
        self._new_panel_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._new_panel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._new_panel_button.clicked.connect(self._request_new_panel)
        self.tabBar().setTabButton(0, QTabBar.ButtonPosition.RightSide, self._new_panel_button)
        self._new_panel_button.setEnabled(True)
        self.tabBar().tabMoved.connect(self._keep_new_panel_tab_last)
        self.tabBar().tabBarClicked.connect(lambda _index: self.activated.emit())
        self.currentChanged.connect(self._current_changed)
        self.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabBar().customContextMenuRequested.connect(self._request_context_menu)
        self.hide()

    def panel_count(self) -> int:
        return self.count() - 1

    def _request_new_panel(self) -> None:
        self.activated.emit()
        panel = self.currentWidget()
        if isinstance(panel, ModulePage):
            self.new_panel_requested.emit(panel)

    def _current_changed(self, _index: int) -> None:
        if self.currentWidget() is not self._new_panel_tab:
            self.activated.emit()

    def _keep_new_panel_tab_last(self, _from: int, _to: int) -> None:
        index = self.indexOf(self._new_panel_tab)
        last = self.count() - 1
        if 0 <= index < last:
            self.tabBar().moveTab(index, last)

    def _request_context_menu(self, point) -> None:
        panel = self.widget(self.tabBar().tabAt(point))
        if panel is not None and panel is not self._new_panel_tab:
            self.context_menu_requested.emit(panel, self.tabBar().mapToGlobal(point))

    def add_panel(self, name: str, panel: QWidget) -> None:
        index = self.insertTab(self.indexOf(self._new_panel_tab), panel, name)
        if isinstance(panel, ModulePage):
            close_button = QToolButton()
            close_button.setObjectName("panelCloseButton")
            close_button.setText("×")
            close_button.setAutoRaise(True)
            close_button.setFixedSize(22, 22)
            close_button.setCursor(Qt.CursorShape.PointingHandCursor)
            close_button.clicked.connect(lambda _checked=False, target=panel: target.close_requested.emit())
            self.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, close_button)
        self.show()

    def take_panel(self, panel: QWidget) -> None:
        index = self.indexOf(panel)
        if index < 0:
            return
        if self.currentWidget() is panel:
            candidates = [position for position in range(self.count()) if position != index and self.isTabEnabled(position)]
            left = [position for position in candidates if position < index]
            if left or candidates:
                self.setCurrentIndex(left[-1] if left else candidates[0])
        self.removeTab(index)
        panel.hide()
