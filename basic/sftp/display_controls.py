"""Presentation controls shared by standalone and in-window transfers."""

from PySide6.QtCore import QEvent, QSignalBlocker, Signal
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QTabBar, QWidget

from common.i18n import tr
from common.i18n.widgets import QPushButton


class TransferDisplayControls(QWidget):
    mode_requested = Signal(str)
    fullscreen_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._mode = "standalone"
        self.mode_tabs = QTabBar(self)
        self.mode_tabs.setObjectName("transferDisplayModeTabs")
        self.mode_tabs.setExpanding(False)
        self.mode_tabs.setDrawBase(False)
        self.mode_tabs.setUsesScrollButtons(False)
        self.mode_tabs.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.mode_tabs.setStyleSheet(
            "QTabBar#transferDisplayModeTabs::tab {"
            " background:palette(base); color:palette(text); border:1px solid palette(mid);"
            " padding:6px 14px; margin:0; }"
            "QTabBar#transferDisplayModeTabs::tab:first { border-top-left-radius:4px; border-bottom-left-radius:4px; }"
            "QTabBar#transferDisplayModeTabs::tab:last { border-left:0; border-top-right-radius:4px; border-bottom-right-radius:4px; }"
            "QTabBar#transferDisplayModeTabs::tab:selected {"
            " background:palette(highlight); color:palette(highlighted-text); font-weight:600; }"
        )
        self.mode_tabs.addTab(tr("独立模式"))
        self.mode_tabs.addTab(tr("窗口模式"))
        self.mode_tabs.currentChanged.connect(self._mode_changed)
        layout.addWidget(self.mode_tabs)
        layout.addStretch(1)
        self.fullscreen_button = QPushButton(tr("全屏"))
        self.fullscreen_button.clicked.connect(lambda _checked=False: self.fullscreen_requested.emit())
        layout.addWidget(self.fullscreen_button)
        self.set_mode("standalone")

    def set_mode(self, mode):
        if mode not in {"standalone", "window"}:
            return
        self._mode = mode
        standalone = mode == "standalone"
        blocker = QSignalBlocker(self.mode_tabs)
        self.mode_tabs.setCurrentIndex(0 if standalone else 1)
        del blocker
        self.fullscreen_button.setVisible(standalone)

    def _mode_changed(self, index):
        if index not in {0, 1}:
            return
        mode = "standalone" if index == 0 else "window"
        if mode != self._mode:
            self.set_mode(mode)
            self.mode_requested.emit(mode)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange and hasattr(self, "mode_tabs"):
            self.mode_tabs.setTabText(0, tr("独立模式"))
            self.mode_tabs.setTabText(1, tr("窗口模式"))

    def set_fullscreen(self, fullscreen):
        self.fullscreen_button.setText(tr("退出全屏") if fullscreen else tr("全屏"))
