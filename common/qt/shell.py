"""Shared application layout without feature-specific UI."""

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QHBoxLayout,
    QSplitter,
    QStackedWidget,
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
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self._background_painter = None
        self._panel_focus_layout: tuple[list[int], list[bool]] | None = None
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

        self.content_stack = QStackedWidget()
        self.content_stack.addWidget(self.editor_container)
        self.content_stack.addWidget(self.bottom_panel)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(5)
        self.main_splitter.addWidget(self.sidebar)
        self.main_splitter.addWidget(self.content_stack)
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
        layout.addWidget(status)
        self.reset_layout()

    def set_background_painter(self, paint) -> None:
        if paint is self._background_painter:
            return
        self._background_painter = paint
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._background_painter is not None:
            painter = QPainter(self)
            self._background_painter(painter)
            painter.end()

    @property
    def panel_focus_mode(self) -> bool:
        return self._panel_focus_layout is not None

    def normal_layout(self) -> tuple[list[int], list[bool]]:
        if self._panel_focus_layout is not None:
            main_sizes, visible = self._panel_focus_layout
            return list(main_sizes), list(visible)
        widgets = (self.toolbar, self.sidebar)
        return (
            self.main_splitter.sizes(),
            [not widget.isHidden() for widget in widgets],
        )

    @property
    def workspace_mode(self) -> bool:
        return self.content_stack.currentWidget() is self.bottom_panel

    def set_workspace_mode(self, enabled: bool) -> None:
        blocker = QSignalBlocker(self.bottom_panel)
        self.content_stack.setCurrentWidget(self.bottom_panel if enabled else self.editor_container)
        del blocker

    def set_panel_focus_mode(self, focused: bool) -> None:
        if focused == self.panel_focus_mode:
            return
        widgets = (self.toolbar, self.sidebar)
        if focused:
            if not self.bottom_panel.has_panels():
                return
            self._panel_focus_layout = (
                self.main_splitter.sizes(),
                [not widget.isHidden() for widget in widgets],
            )
            self.toolbar.hide()
            self.sidebar.hide()
            self.set_workspace_mode(True)
            self.main_splitter.setSizes([0, max(1, self.main_splitter.width())])
        else:
            main_sizes, visible = self._panel_focus_layout
            self._panel_focus_layout = None
            for widget, show in zip(widgets, visible):
                widget.setVisible(show)
            self.main_splitter.setSizes(main_sizes)
        self.bottom_panel.set_panel_focus(focused)

    def reset_layout(self) -> None:
        self.set_panel_focus_mode(False)
        self.main_splitter.setSizes([280, 820])
