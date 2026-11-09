"""Main content area storing pages by their public identifiers."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from common.i18n import tr
from common.i18n.widgets import QLabel


class PageContainer(QStackedWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("mainPages")
        self._pages: dict[str, QWidget] = {}

        empty_page = QWidget()
        layout = QVBoxLayout(empty_page)
        title = QLabel("PipeTerminal")
        title.setObjectName("welcomeTitle")
        hint = QLabel(tr("从左侧选择模块开始"))
        hint.setObjectName("welcomeHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addStretch(1)
        self.addWidget(empty_page)

    def add_page(self, page_id: str, page: QWidget) -> None:
        if page_id in self._pages:
            raise ValueError(tr("页面已存在：{0}", page_id))
        self.addWidget(page)
        self._pages[page_id] = page

    def show_page(self, page_id: str) -> None:
        self.setCurrentWidget(self._pages[page_id])
