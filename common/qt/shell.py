"""Shared application layout without feature-specific UI."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QProgressBar,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from common.i18n import tr
from common.i18n.widgets import QLabel

from .bottom_panel import BottomPanel
from .page_container import PageContainer
from .sidebar import Sidebar
from .toolbar import Toolbar


class ApplicationShell(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("applicationShell")
        self._panel_focus_layout: tuple[list[int], list[int], list[bool]] | None = None
        self._workspace_mode = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.toolbar = Toolbar()
        layout.addWidget(self.toolbar)

        self.sidebar = Sidebar()
        self.pages = PageContainer()
        self.bottom_panel = BottomPanel()
        self.editor_container = QWidget()
        editor_layout = QVBoxLayout(self.editor_container)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(0)
        self.editor_toolbar = Toolbar()
        self.editor_toolbar.setObjectName("editorToolbar")
        editor_layout.addWidget(self.editor_toolbar)
        editor_layout.addWidget(self.pages, 1)

        self.right_splitter = QSplitter(Qt.Orientation.Vertical)
        self.right_splitter.setChildrenCollapsible(False)
        self.right_splitter.setHandleWidth(5)
        self.right_splitter.setOpaqueResize(True)
        self.right_splitter.addWidget(self.editor_container)
        self.right_splitter.addWidget(self.bottom_panel)
        self.right_splitter.handle(1).setCursor(Qt.CursorShape.SplitVCursor)
        self.right_splitter.setStretchFactor(0, 1)
        self.right_splitter.setStretchFactor(1, 0)
        self.bottom_panel.hide()

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(5)
        self.main_splitter.addWidget(self.sidebar)
        self.main_splitter.addWidget(self.right_splitter)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        layout.addWidget(self.main_splitter, 1)

        status = QWidget()
        status.setObjectName("applicationStatusBar")
        status_layout = QHBoxLayout(status)
        status_layout.setContentsMargins(14, 5, 14, 5)
        status_layout.setSpacing(16)
        self.status_label = QLabel(tr("就绪"))
        self.status_label.setObjectName("applicationStatusText")
        status_layout.addWidget(self.status_label, 1)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedWidth(150)
        self.progress_bar.setObjectName("applicationProgress")
        status_layout.addWidget(self.progress_bar)
        layout.addWidget(status)
        self.reset_layout()

    @property
    def panel_focus_mode(self) -> bool:
        return self._panel_focus_layout is not None

    def normal_layout(self) -> tuple[list[int], list[int], list[bool]]:
        if self._panel_focus_layout is not None:
            main_sizes, right_sizes, visible = self._panel_focus_layout
            return list(main_sizes), list(right_sizes), list(visible)
        widgets = (self.toolbar, self.sidebar, self.editor_container, self.bottom_panel)
        return (
            self.main_splitter.sizes(), self.right_splitter.sizes(),
            [not widget.isHidden() for widget in widgets],
        )

    def set_workspace_mode(self, enabled: bool) -> None:
        self._workspace_mode = enabled
        self.editor_container.setVisible(not enabled and not self.panel_focus_mode)
        if enabled:
            self.bottom_panel.show()

    def set_panel_focus_mode(self, focused: bool) -> None:
        if focused == self.panel_focus_mode:
            return
        widgets = (self.toolbar, self.sidebar, self.editor_container, self.bottom_panel)
        if focused:
            if not self.bottom_panel.has_panels():
                return
            self._panel_focus_layout = (
                self.main_splitter.sizes(), self.right_splitter.sizes(),
                [not widget.isHidden() for widget in widgets],
            )
            self.toolbar.hide()
            self.sidebar.hide()
            self.editor_container.hide()
            self.bottom_panel.show()
            self.main_splitter.setSizes([0, max(1, self.main_splitter.width())])
            self.right_splitter.setSizes([0, max(1, self.right_splitter.height())])
        else:
            main_sizes, right_sizes, visible = self._panel_focus_layout
            self._panel_focus_layout = None
            for widget, show in zip(widgets, visible):
                widget.setVisible(show)
            self.editor_container.setVisible(not self._workspace_mode)
            if self._workspace_mode:
                self.bottom_panel.show()
            self.main_splitter.setSizes(main_sizes)
            self.right_splitter.setSizes(right_sizes)
        self.bottom_panel.set_panel_focus(focused)

    def reset_layout(self) -> None:
        self.set_panel_focus_mode(False)
        self.main_splitter.setSizes([280, 820])
        self.right_splitter.setSizes([370, 380])
