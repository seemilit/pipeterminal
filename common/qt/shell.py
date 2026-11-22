"""Shared application layout without feature-specific UI."""

from PySide6.QtCore import QSignalBlocker, QSize, Qt
from PySide6.QtGui import QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
    QTreeWidget,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from common.i18n import tr
from common.i18n.widgets import QLabel, QToolButton

from .bottom_panel import BottomPanel
from .page_container import PageContainer
from .sidebar import Sidebar
from .toolbar import Toolbar
from .workspace_tabs import WorkspaceTabs


class _SessionSidebarToggle(QToolButton):
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.setPen(QPen(self.palette().color(QPalette.ColorRole.ButtonText), 1.5))
        direction = -1 if self.isChecked() else 1
        for center in (-3, 3):
            tip = center + 2 * direction
            tail = center - 2 * direction
            painter.drawLine(tail, -4, tip, 0)
            painter.drawLine(tip, 0, tail, 4)
        painter.end()


class ApplicationShell(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("applicationShell")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self._background_painter = None
        self._panel_focus_layout: tuple[list[int], list[bool]] | None = None
        self._session_focus = False
        self._home_focus_layout: tuple[list[int], list[bool]] | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tabs = WorkspaceTabs(self)
        tab_row = QHBoxLayout()
        tab_row.setContentsMargins(0, 0, 8, 0)
        tab_row.setSpacing(6)
        self.tabs.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        tab_row.addWidget(self.tabs)
        self.workspace_add_button = QToolButton()
        self.workspace_add_button.setObjectName("panelAddButton")
        self.workspace_add_button.setText("+")
        self.workspace_add_button.setToolTip(tr("新建页签"))
        self.workspace_add_button.setAutoRaise(True)
        self.workspace_add_button.setFixedSize(26, 26)
        self.workspace_add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.workspace_add_button.hide()
        tab_row.addWidget(self.workspace_add_button)
        tab_row.addStretch(1)
        self.background_runs = QToolButton()
        self.background_runs.setText(tr("后台任务"))
        self.background_runs.hide()
        tab_row.addWidget(self.background_runs)
        self.workspace_focus_button = QToolButton()
        self.workspace_focus_button.setObjectName("directoryActionButton")
        self.workspace_focus_button.setFixedSize(30, 26)
        self.workspace_focus_button.setIconSize(QSize(16, 16))
        self.workspace_focus_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.workspace_focus_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.workspace_focus_button.hide()
        tab_row.addWidget(self.workspace_focus_button)
        self.workspace_settings_button = QToolButton()
        self.workspace_settings_button.setObjectName("directoryActionButton")
        self.workspace_settings_button.setFixedSize(30, 26)
        self.workspace_settings_button.setIconSize(QSize(16, 16))
        self.workspace_settings_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.workspace_settings_button.setText(tr("设置"))
        self.workspace_settings_button.setToolTip(tr("设置"))
        self.workspace_settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.workspace_settings_button.hide()
        tab_row.addWidget(self.workspace_settings_button)
        layout.addLayout(tab_row)
        self.toolbar = Toolbar(collapse_when_empty=True)
        self.toolbar.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self.sidebar = Sidebar()
        self.pages = PageContainer()
        self.bottom_panel = BottomPanel()
        self.editor_container = QWidget()
        editor_layout = QVBoxLayout(self.editor_container)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(0)
        self.editor_toolbar = Toolbar(collapse_when_empty=True)
        self.editor_toolbar.setObjectName("editorToolbar")
        editor_layout.addWidget(self.editor_toolbar)
        editor_layout.addWidget(self.pages, 1)

        self.content_stack = QStackedWidget()
        self.content_stack.addWidget(self.editor_container)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(5)
        self.main_splitter.addWidget(self.sidebar)
        self.main_splitter.addWidget(self.content_stack)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.home = QWidget()
        home_layout = QVBoxLayout(self.home)
        home_layout.setContentsMargins(0, 0, 0, 0)
        home_layout.setSpacing(0)
        home_layout.addWidget(self.toolbar)
        home_layout.addWidget(self.main_splitter, 1)
        self.runtime_page = QWidget()
        runtime_layout = QHBoxLayout(self.runtime_page)
        runtime_layout.setContentsMargins(0, 0, 0, 0)
        runtime_layout.setSpacing(0)
        self.runtime = QSplitter(Qt.Orientation.Horizontal)
        runtime_layout.addWidget(self.runtime, 1)
        self.runtime.setChildrenCollapsible(False)
        self._expanded_session_width = 220
        self._sessions_expanded = True
        self.session_sidebar = QWidget()
        self._session_sidebar_layout = QGridLayout(self.session_sidebar)
        self._session_sidebar_layout.setContentsMargins(0, 0, 0, 0)
        self._session_sidebar_layout.setSpacing(0)
        self._session_sidebar_layout.setColumnStretch(0, 1)
        self._session_sidebar_layout.setColumnMinimumWidth(1, 16)

        self.sessions = QTreeWidget()
        self.sessions.setHeaderHidden(True)
        self.sessions.setMinimumWidth(170)
        self.sessions.setObjectName("workspaceSessions")
        self._session_sidebar_layout.addWidget(self.sessions, 0, 0, 1, 2)

        self.session_toggle = _SessionSidebarToggle()
        self.session_toggle.setObjectName("workspaceSessionsToggle")
        self.session_toggle.setFixedSize(28, 26)
        self.session_toggle.setCheckable(True)
        self.session_toggle.setChecked(self._sessions_expanded)
        self.session_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.session_toggle.setToolTip(tr("收起会话列表"))
        self.session_toggle.clicked.connect(lambda: self._set_sessions_visible(not self._sessions_expanded))
        self._session_sidebar_layout.addWidget(
            self.session_toggle, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight
        )
        self.runtime.addWidget(self.session_sidebar)
        self.runtime.addWidget(self.bottom_panel)
        self.runtime.setStretchFactor(1, 1)
        self.runtime.setSizes([self._expanded_session_width, 880])
        self.workspace_stack = QStackedWidget()
        self.workspace_stack.addWidget(self.home)
        self.workspace_stack.addWidget(self.runtime_page)
        layout.addWidget(self.workspace_stack, 1)

        status = self._status_bar = QWidget()
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

    @property
    def workspace_focused(self) -> bool:
        return self._session_focus or self._home_focus_layout is not None

    def normal_layout(self) -> tuple[list[int], list[bool]]:
        saved_layout = self._home_focus_layout or self._panel_focus_layout
        if saved_layout is not None:
            main_sizes, visible = saved_layout
            return list(main_sizes), list(visible)
        widgets = (self.toolbar, self.sidebar)
        return (
            self.main_splitter.sizes(),
            [not widget.isHidden() for widget in widgets],
        )

    @property
    def workspace_mode(self) -> bool:
        return self.workspace_stack.currentWidget() is self.runtime_page

    def _set_sessions_visible(self, visible: bool) -> None:
        if not visible:
            self._expanded_session_width = self.runtime.sizes()[0]
        self._sessions_expanded = visible
        self._update_runtime_sidebar()
        if visible:
            self.runtime.setSizes([
                self._expanded_session_width,
                max(1, self.runtime_page.width() - self._expanded_session_width - self.runtime.handleWidth()),
            ])
        self.session_toggle.setChecked(visible)
        self.session_toggle.setToolTip(tr("收起会话列表" if visible else "展开会话列表"))

    def _update_runtime_sidebar(self) -> None:
        if self._session_focus:
            self.session_sidebar.hide()
            self.session_toggle.hide()
            return
        toggle_had_focus = self.session_toggle.hasFocus()
        if self._sessions_expanded:
            if self._session_sidebar_layout.indexOf(self.session_toggle) < 0:
                self._session_sidebar_layout.addWidget(
                    self.session_toggle, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight
                )
                self.session_toggle.raise_()
        else:
            runtime_layout = self.runtime_page.layout()
            if runtime_layout.indexOf(self.session_toggle) < 0:
                runtime_layout.insertWidget(0, self.session_toggle, 0, Qt.AlignmentFlag.AlignTop)
        self.session_sidebar.setVisible(self._sessions_expanded)
        self.session_toggle.show()
        if toggle_had_focus:
            self.session_toggle.setFocus()

    def set_workspace_focus(self, focused: bool, *, panel_status: bool = False) -> None:
        self._status_bar.setVisible(not (focused and panel_status))
        home_focused = focused and not self.workspace_mode
        if home_focused and self._home_focus_layout is None:
            self._home_focus_layout = self.normal_layout()
            self.toolbar.hide()
            self.sidebar.hide()
        elif not home_focused and self._home_focus_layout is not None:
            sizes, visible = self._home_focus_layout
            self._home_focus_layout = None
            self.toolbar.setVisible(visible[0])
            self.sidebar.setVisible(visible[1])
            self.main_splitter.setSizes(sizes)

        session_focused = focused and self.workspace_mode
        if session_focused == self._session_focus:
            return
        if session_focused and self._sessions_expanded and self.runtime.sizes()[0] > 0:
            self._expanded_session_width = self.runtime.sizes()[0]
        self._session_focus = session_focused
        if not session_focused and self._sessions_expanded:
            self._set_sessions_visible(True)
        else:
            self._update_runtime_sidebar()

    def set_workspace_mode(self, enabled: bool) -> None:
        blocker = QSignalBlocker(self.bottom_panel)
        self.workspace_stack.setCurrentWidget(self.runtime_page if enabled else self.home)
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
            self.set_workspace_mode(True)
        else:
            main_sizes, visible = self._panel_focus_layout
            self._panel_focus_layout = None
            for widget, show in zip(widgets, visible):
                widget.setVisible(show)
            self.main_splitter.setSizes(main_sizes)

    def reset_layout(self) -> None:
        self.set_panel_focus_mode(False)
        self.main_splitter.setSizes([280, 820])
