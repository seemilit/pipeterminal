"""Build one shared Qt stylesheet from theme tokens."""

from .palettes import ThemePalette


def build_stylesheet(theme: ThemePalette, *, translucent_workspace: bool = False) -> str:
    stylesheet = f"""
QWidget {{ color: {theme.foreground}; }}
QLabel#pageTitle {{ font-size: 20px; font-weight: 600; }}
QLabel#secondaryText {{ color: {theme.muted}; }}
QMainWindow, QDialog, QWidget#applicationShell {{ background: {theme.background}; }}
QFrame#mainToolbar {{ background: {theme.surface}; border: 0; border-bottom: 1px solid {theme.border}; }}
QFrame#editorToolbar {{ background: {theme.surface}; border: 0; border-bottom: 1px solid {theme.border}; }}
QTabBar#workspaceTabs::tab {{
    background: {theme.sidebar}; border: 1px solid {theme.border}; border-bottom: 0;
    border-top-left-radius: 6px; border-top-right-radius: 6px;
    margin: 3px 2px 0 0; padding: 6px 9px; max-width: 210px;
}}
QTabBar#workspaceTabs::tab:selected {{ background: {theme.surface}; border-color: {theme.accent}; }}
QTabBar#workspaceTabs[workspaceEmpty="true"]::tab:selected {{ background: {theme.sidebar}; border-color: {theme.border}; }}
QTabBar#workspaceTabs::tab:hover {{ background: {theme.hover}; }}
QTreeWidget#workspaceSessions {{ background: {theme.sidebar}; border: 0; padding: 6px; }}
QTreeWidget#workspaceSessions::item {{ min-height: 26px; }}
QToolButton#workspaceSessionsToggle {{
    background: transparent; color: {theme.foreground};
    border: 1px solid transparent; border-radius: 4px; padding: 0;
}}
QToolButton#workspaceSessionsToggle:hover {{
    background: {theme.hover};
}}
QToolButton#workspaceSessionsToggle:focus {{
    border-color: {theme.accent};
}}
QToolButton#workspaceSessionsToggle:pressed {{
    background: {theme.selection}; color: {theme.selection_text};
}}
QWidget#applicationStatusBar {{ background: {theme.sidebar}; border-top: 1px solid {theme.border}; }}
QLabel#applicationStatusText {{ color: {theme.muted}; }}
QFrame#bottomPanel, QStackedWidget#mainPages {{
    background: {theme.surface}; border: 0; border-radius: 0;
}}
QFrame#moduleSidebar {{ background: {theme.surface}; border: 0; border-right: 1px solid {theme.border}; }}
QWidget#moduleNavigation {{ background: {theme.sidebar}; border-right: 1px solid {theme.border}; }}
QFrame#directoryPanel {{ background: {theme.surface}; border: 0; }}
QWidget#directoryHeader {{ background: {theme.surface}; border-bottom: 1px solid {theme.border}; }}
QLabel#directoryHeading {{ color: {theme.foreground}; font-weight: 600; }}
QLabel#directoryCount {{ background: {theme.sidebar}; color: {theme.muted}; border-radius: 7px; padding: 2px 7px; }}
QLabel#welcomeTitle {{ color: {theme.foreground}; font-size: 28px; font-weight: 600; margin-bottom: 4px; }}
QLabel#welcomeHint {{ color: {theme.muted}; font-size: 13px; }}
QPushButton, QToolButton {{
    background: {theme.surface}; border: 1px solid {theme.border}; border-radius: 5px;
    padding: 5px 12px; min-height: 22px;
}}
QPushButton:hover:enabled, QToolButton:hover:enabled {{ background: {theme.hover}; border-color: {theme.accent}; }}
QPushButton:pressed, QToolButton:pressed, QToolButton:checked {{
    background: {theme.selection}; border-color: {theme.accent}; color: {theme.selection_text};
}}
QPushButton:focus:enabled {{ border-color: {theme.accent}; }}
QPushButton[dialogPrimary="true"]:enabled {{
    background: {theme.accent}; color: {theme.accent_text}; border-color: {theme.accent};
}}
QPushButton[dialogPrimary="true"]:hover:enabled, QPushButton[dialogPrimary="true"]:focus:enabled {{
    border-color: {theme.foreground};
}}
QPushButton[dialogPrimary="true"]:pressed:enabled {{
    background: {theme.selection}; color: {theme.selection_text};
}}
QPushButton:disabled, QToolButton:disabled {{ color: {theme.muted}; border-color: {theme.border}; }}
QToolButton#toolbarActionButton {{
    background: transparent; border: 1px solid transparent; padding: 0 10px;
    min-width: 0; min-height: 32px; max-height: 32px; border-radius: 6px; font-size: 13px;
}}
QToolButton#editorActionButton {{
    background: transparent; border: 1px solid transparent; padding: 0 10px;
    min-width: 0; min-height: 30px; max-height: 30px; border-radius: 6px;
}}
QToolButton#toolbarActionButton:hover:enabled, QToolButton#editorActionButton:hover:enabled {{ background: {theme.hover}; border-color: {theme.border}; }}
QToolButton#directoryActionButton {{
    background: transparent; border: 1px solid transparent; border-radius: 5px; padding: 0;
}}
QToolButton#directoryActionButton:hover:enabled {{ background: {theme.hover}; border-color: {theme.border}; }}
QToolButton#directoryActionButton:pressed:enabled {{ background: {theme.selection}; border-color: {theme.accent}; }}
QToolButton#directoryActionButton:focus:enabled {{ border-color: {theme.accent}; }}
QToolButton#toolbarActionButton[primary="true"]:enabled {{ background: {theme.accent}; color: {theme.accent_text}; border-color: {theme.accent}; }}
QToolButton#toolbarActionButton[primary="true"]:hover:enabled {{ background: {theme.accent}; color: {theme.accent_text}; border-color: {theme.foreground}; }}
QToolButton#toolbarActionButton[primary="true"]:pressed:enabled {{ background: {theme.selection}; color: {theme.selection_text}; border-color: {theme.accent}; }}
QFrame#serverConnectionCard, QFrame#serverAccessPathsCard {{
    background: {theme.surface}; border: 1px solid {theme.border}; border-radius: 8px;
}}
QWidget#serverConfigurationPage {{ background: {theme.background}; }}
QWidget#taskEditor {{ background: {theme.background}; }}
QFrame#taskPanel, QFrame#taskOutputPanel {{
    border: 1px solid {theme.border}; border-radius: 8px; background: {theme.surface};
}}
QLabel#taskHeading {{ font-size: 20px; font-weight: 600; }}
QLabel#taskMetadata {{ color: {theme.muted}; padding: 0 12px; }}
QLabel#panelHeading {{ font-weight: 600; padding: 2px 0 6px 0; }}
QFrame#taskToolBar {{ background: {theme.surface}; border: 1px solid {theme.border}; border-radius: 8px; }}
QFrame#taskToolBar QPushButton {{
    background: transparent; border: 1px solid transparent; padding: 4px 8px; min-height: 24px;
}}
QFrame#taskToolBar QPushButton:hover:enabled {{ background: {theme.hover}; border-color: {theme.border}; }}
QFrame#taskToolBar QPushButton:checked {{
    background: {theme.selection}; color: {theme.selection_text}; border-color: {theme.border};
}}
QPushButton#taskExecuteButton:enabled {{
    background: {theme.accent}; color: {theme.accent_text}; border-color: {theme.accent};
    min-width: 80px; padding: 6px 16px; font-weight: 600;
}}
QPushButton#taskExecuteButton:hover:enabled {{ border-color: {theme.foreground}; }}
QFrame#taskRunBar {{ background: {theme.surface}; border: 1px solid {theme.border}; border-radius: 8px; }}
QLabel#taskRunStatus {{ color: {theme.muted}; padding: 4px 8px; font-weight: 600; }}
QLabel#taskRunStatus[runState="running"] {{ color: {theme.accent}; }}
QLabel#taskRunStatus[runState="failed"] {{ color: {"#fca5a5" if theme.dark else "#b42318"}; }}
QLabel#taskRunStatus[runState="success"] {{ color: {"#86efac" if theme.dark else "#18794e"}; }}
QPlainTextEdit#taskParameterPreview {{ border: 0; padding: 8px; }}
QTabWidget#taskParameterTabs::pane {{ border: 0; border-top: 1px solid {theme.border}; }}
QFrame#themeSection {{ background: {theme.surface}; border: 1px solid {theme.border}; border-radius: 8px; }}
QTreeWidget#taskModuleLibrary {{ background: palette(base); border: none; }}
QLabel#configurationSectionHeading {{ font-weight: 600; font-size: 14px; }}
QFrame#serverAccessPathRow {{
    background: {theme.surface}; border: 1px solid transparent; border-radius: 4px;
}}
QFrame#serverAccessPathRow[active="true"] {{ background: {theme.selection}; border-color: {theme.accent}; }}
QFrame#serverAccessPathRow[active="true"] QLabel {{ color: {theme.selection_text}; }}
QScrollArea#serverConfigurationForm QLineEdit {{ padding: 4px 11px; min-height: 24px; max-height: 24px; }}
QScrollArea#serverConfigurationForm QPushButton {{
    padding: 3px 10px; min-width: 66px; min-height: 24px; max-height: 24px;
}}
QToolButton#passwordVisibilityButton {{
    background: transparent; border: 1px solid transparent; padding: 0; min-height: 0;
}}
QToolButton#passwordVisibilityButton:hover {{ background: {theme.hover}; }}
QToolButton#passwordVisibilityButton:focus {{ border-color: {theme.accent}; }}
QCheckBox#pathOption {{ padding: 2px 4px; background: transparent; border: 0; }}
QWidget#shellHeader QPushButton, QWidget#shellCommandBar QPushButton {{
    padding: 3px 8px; min-width: 66px;
    min-height: 22px; max-height: 22px; border-radius: 4px;
}}
QWidget#shellCommandBar QPushButton#shellFilePanelButton {{ min-width: 18px; max-width: 18px; }}
QWidget#shellCommandBar QLineEdit {{ padding: 2px 8px; min-height: 24px; max-height: 24px; }}
QTabWidget#bottomPanelTabs QTabBar::tab {{
    background: {theme.sidebar}; color: {theme.foreground};
    border: 1px solid {theme.border}; border-top: 2px solid transparent; border-radius: 0;
    margin: 0 3px 0 0; padding: 5px 12px; min-height: 24px;
}}
QTabWidget#bottomPanelTabs QTabBar::tab:hover {{
    background: {theme.hover};
}}
QTabWidget#bottomPanelTabs QTabBar::tab:selected {{
    background: {theme.surface}; color: {theme.foreground};
    border-top-color: {theme.accent}; border-bottom-color: {theme.surface};
}}
QTabWidget#bottomPanelTabs QTabBar::tab:last:disabled {{
    background: transparent; border: 0; margin: 2px 0 0; padding: 0 4px; min-height: 26px;
}}
QToolButton#panelAddButton {{
    background: transparent; color: {theme.muted}; padding: 0; border: 0;
    min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px;
    border-radius: 2px; font-size: 18px; font-weight: 600;
}}
QToolButton#panelAddButton:hover {{
    background: {theme.hover}; color: {theme.foreground};
}}
QToolButton#panelAddButton:pressed {{
    background: {theme.selection}; color: {theme.selection_text};
}}
QTabWidget#bottomPanelTabs QToolButton#ScrollLeftButton,
QTabWidget#bottomPanelTabs QToolButton#ScrollRightButton {{
    padding: 0; min-width: 0; min-height: 0; border-radius: 3px;
    qproperty-iconSize: 20px 20px;
}}
QToolButton#panelCloseButton {{
    background: transparent; color: {theme.muted}; padding: 0; border: 0;
    min-width: 22px; max-width: 22px; min-height: 22px; max-height: 22px;
    border-radius: 2px; font-size: 14px; font-weight: 400;
}}
QToolButton#panelCloseButton:hover {{
    background: {theme.hover}; color: {theme.foreground};
}}
QToolButton#panelCloseButton:pressed {{
    background: {theme.selection}; color: {theme.selection_text};
}}
QWidget#serverStatusPanel {{ background: {theme.surface}; }}
QWidget#serverStatusPanel QLabel#monitorTitle {{ font-weight: 600; padding: 4px 0; }}
QWidget#serverStatusPanel QLabel#monitorStatus {{ color: {theme.muted}; }}
QWidget#serverStatusPanel QProgressBar {{ min-height: 20px; max-height: 20px; }}
QPushButton#helpButton {{
    color: {theme.accent}; padding: 0;
    min-width: 22px; max-width: 22px; min-height: 22px; max-height: 22px;
    border-radius: 0; font-weight: 600; font-size: 14px; text-align: center;
}}
QPushButton#authPasswordButton, QPushButton#authKeyButton {{
    background: {theme.surface}; color: {theme.foreground};
    border: 1px solid {theme.border}; border-radius: 0;
    padding: 3px 12px; min-width: 62px; min-height: 20px; max-height: 20px;
}}
QScrollArea#serverConfigurationForm QPushButton#authPasswordButton,
QScrollArea#serverConfigurationForm QPushButton#authKeyButton {{
    padding: 3px 12px; min-width: 62px; min-height: 20px; max-height: 20px;
}}
QPushButton#authPasswordButton {{ border-top-left-radius: 4px; border-bottom-left-radius: 4px; }}
QPushButton#authKeyButton {{ border-left: 0; border-top-right-radius: 4px; border-bottom-right-radius: 4px; }}
QPushButton#authPasswordButton:hover, QPushButton#authKeyButton:hover {{ background: {theme.hover}; }}
QPushButton#authPasswordButton:checked, QPushButton#authKeyButton:checked {{
    background: {theme.selection}; color: {theme.selection_text}; font-weight: 600;
}}
QToolButton#sidebarModuleButton {{
    background: transparent; border: 1px solid transparent; border-radius: 8px;
    font-size: 12px; font-weight: 500; padding: 7px 0; min-height: 40px;
}}
QToolButton#sidebarModuleButton:hover {{ background: {theme.hover}; border-color: {theme.border}; }}
QToolButton#sidebarModuleButton:checked {{
    background: {theme.selection}; color: {theme.selection_text}; border-color: {theme.border};
}}
QListWidget, QTreeWidget, QAbstractItemView, QLineEdit, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {theme.surface}; color: {theme.foreground};
    border: 1px solid {theme.border}; border-radius: 5px;
    selection-background-color: {theme.selection}; selection-color: {theme.selection_text};
}}
QLineEdit, QComboBox {{ padding: 4px 8px; min-height: 22px; }}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {theme.accent}; }}
QPushButton:focus, QToolButton:focus {{ border-color: {theme.accent}; }}
QSpinBox, QDoubleSpinBox {{
    background: {theme.surface}; color: {theme.foreground}; border: 1px solid {theme.border};
    border-radius: 5px; padding: 4px 8px; min-height: 22px;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {theme.accent}; }}
QDialog#settingsDialog QGroupBox {{
    background: {theme.surface}; border: 1px solid {theme.border}; border-radius: 8px;
    margin-top: 12px; padding: 20px 12px 12px;
}}
QDialog#settingsDialog QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 16px; padding: 0 6px; color: {theme.foreground}; font-weight: 600;
}}
QWidget#logPage {{ background: {theme.background}; }}
QWidget#logPage QPlainTextEdit {{ padding: 12px; border-radius: 8px; }}
QAbstractItemView::item:disabled {{ color: {theme.muted}; }}
QMenu::item:disabled {{ color: {theme.muted}; }}
QComboBox::drop-down {{ width: 26px; border: 0; }}
QComboBox {{ combobox-popup: 0; }}
QComboBox QAbstractItemView {{ border: 1px solid {theme.border}; padding: 2px; outline: 0; }}
QComboBox QAbstractItemView::item {{ min-height: 26px; padding: 2px 8px; }}
QListWidget#directoryList {{ border: 0; border-radius: 0; outline: 0; padding: 8px 6px; }}
QListWidget#directoryList::item {{ min-height: 32px; padding: 4px 12px; border: 0; border-left: 3px solid transparent; border-radius: 5px; }}
QListWidget#directoryList::item:hover {{ background: {theme.hover}; }}
QListWidget#directoryList::item:selected {{ background: {theme.selection}; color: {theme.selection_text}; border-left-color: {theme.accent}; }}
QHeaderView::section {{ background: {theme.sidebar}; color: {theme.muted}; border: 0; border-bottom: 1px solid {theme.border}; padding: 8px 12px; font-weight: 500; }}
QTabWidget::pane {{ background: {theme.surface}; border: 1px solid {theme.border}; }}
QTabBar::tab {{ background: {theme.sidebar}; border: 0; padding: 6px 12px; }}
QTabBar::tab:selected {{ background: {theme.surface}; border-bottom: 2px solid {theme.accent}; }}
QSplitter::handle {{ background: {theme.background}; }}
QSplitter::handle:hover {{ background: {theme.border}; }}
QProgressBar {{
    background: {theme.sidebar}; border: 1px solid {theme.border}; border-radius: 4px;
    text-align: center; min-height: 16px;
}}
QProgressBar::chunk {{ background: {theme.accent}; border-radius: 3px; }}
QMenu {{ background: {theme.surface}; border: 1px solid {theme.border}; padding: 6px; }}
QMenu::item {{ padding: 7px 24px; border-radius: 4px; }}
QMenu::item:selected {{ background: {theme.selection}; color: {theme.selection_text}; }}
QToolTip {{ background: {theme.surface}; color: {theme.foreground}; border: 1px solid {theme.border}; padding: 5px 8px; }}
QScrollBar:vertical {{ background: {theme.surface}; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: {theme.surface}; height: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {theme.border}; min-height: 24px; border-radius: 4px; }}
QScrollBar::handle:horizontal {{ background: {theme.border}; min-width: 24px; border-radius: 4px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""
    if not translucent_workspace:
        return stylesheet

    surface_rgb = ", ".join(str(int(theme.surface[index:index + 2], 16)) for index in (1, 3, 5))
    return stylesheet + f"""
#applicationShell QFrame#mainToolbar, #applicationShell QFrame#editorToolbar,
#applicationShell QFrame#moduleSidebar, #applicationShell QFrame#directoryPanel,
#applicationShell QWidget#directoryHeader, #applicationShell QWidget#moduleNavigation,
#applicationShell QFrame#bottomPanel, #applicationShell QStackedWidget#mainPages,
#applicationShell QWidget#serverConfigurationPage, #applicationShell QWidget#taskEditor,
#applicationShell QTabWidget#bottomPanelTabs::pane,
#applicationShell QTabWidget#taskParameterTabs::pane {{
    background: transparent;
}}
#applicationShell QFrame#taskPanel, #applicationShell QFrame#serverConnectionCard,
#applicationShell QFrame#serverAccessPathsCard, #applicationShell QWidget[workspaceSurface="true"] {{
    background: rgba({surface_rgb}, 232);
}}
#applicationShell QFrame#serverAccessPathRow[active="false"],
#applicationShell QFrame#moduleSidebar QAbstractItemView,
#applicationShell QFrame#taskPanel QTreeWidget#taskModuleLibrary,
#applicationShell QWidget[workspaceSurface="true"] QAbstractItemView,
#applicationShell QPlainTextEdit#taskParameterPreview,
#applicationShell QScrollArea#serverConfigurationForm,
#applicationShell QScrollArea#serverConfigurationForm > QWidget#qt_scrollarea_viewport {{
    background: transparent;
}}
"""
