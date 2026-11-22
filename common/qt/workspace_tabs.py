"""Global session tabs with a fixed home entry and existing panel drag protocol."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTabBar
from common.i18n import tr
from .panel_tab_bar import PanelTabBar


class WorkspaceTabs(PanelTabBar):
    home_requested = Signal()
    panel_requested = Signal(object)
    panel_close_requested = Signal(object)
    panel_menu_requested = Signal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.group = self
        self.setObjectName("workspaceTabs")
        self.setMovable(True)
        self.setTabsClosable(True)
        self.setExpanding(False)
        self.setUsesScrollButtons(True)
        self.setElideMode(Qt.TextElideMode.ElideRight)
        self.addTab(tr("主面板"))
        self.setTabButton(0, QTabBar.ButtonPosition.RightSide, None)
        self.setTabButton(0, QTabBar.ButtonPosition.LeftSide, None)
        self.currentChanged.connect(self._activate)
        self.tabBarClicked.connect(self._open_home_from_empty_workspace)
        self.tabCloseRequested.connect(self._close)
        self.tabMoved.connect(self._keep_home)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def widget(self, index):
        return self.tabData(index) if index >= 0 else None

    def indexOf(self, panel):
        return next((index for index in range(self.count()) if self.widget(index) is panel), -1)

    def currentWidget(self):
        return self.widget(self.currentIndex())

    def _keep_home(self, *_args):
        index = self.indexOf(None)
        if index > 0:
            self.moveTab(index, 0)

    def _activate(self, index):
        panel = self.widget(index)
        if panel is None:
            self.home_requested.emit()
        else:
            self.panel_requested.emit(panel)

    def set_workspace_empty(self, empty: bool) -> None:
        if bool(self.property("workspaceEmpty")) == empty:
            return
        self.setProperty("workspaceEmpty", empty)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def _open_home_from_empty_workspace(self, index):
        if index == 0 and self.property("workspaceEmpty"):
            self.home_requested.emit()

    def _close(self, index):
        panel = self.widget(index)
        if panel is not None:
            self.panel_close_requested.emit(panel)

    def _menu(self, point):
        panel = self.widget(self.tabAt(point))
        if panel is not None:
            self.panel_menu_requested.emit(panel, self.mapToGlobal(point))

    def add_panel(self, panel, name):
        index = self.indexOf(panel)
        if index < 0:
            index = self.addTab(name)
            self.setTabData(index, panel)
        self.setTabText(index, name)
        self.setTabToolTip(index, name)
        return index
