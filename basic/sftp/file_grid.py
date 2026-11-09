"""Compact file tiles sharing the detail view's model and selection."""

import math

from PySide6.QtCore import QEvent, QPointF, QRect, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPalette, QTextLayout, QTextOption
from PySide6.QtWidgets import QListView, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from .drag_drop import REMOTE_FILES_MIME, _TransferDrag
from .file_links import underline_file_link


FILE_VIEW_MODES = (
    ("details", "详细列表"), ("list", "横向列表"), ("small", "小图标"),
    ("medium", "中图标"), ("large", "大图标"),
)

_GRID_MODES = {"list": (220, 16, False), "small": (150, 16, False),
               "medium": (150, 48, True), "large": (190, 72, True)}


def _name_layout(name, font, width, alignment=Qt.AlignmentFlag.AlignLeft):
    layout = QTextLayout(name, font)
    options = QTextOption()
    options.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    options.setAlignment(alignment)
    layout.setTextOption(options)
    layout.beginLayout()
    height = 0.0
    while True:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(max(1, width))
        line.setPosition(QPointF(0, height))
        height += line.height()
    layout.endLayout()
    return layout, height


class _FileIconDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return self.parent().gridSize()

    def paint(self, painter, option, index):
        view = self.parent()
        option = QStyleOptionViewItem(option)
        self.initStyleOption(option, index)
        underline_file_link(option, index, view)
        entry = index.data(Qt.ItemDataRole.UserRole)
        name = entry.name if entry is not None else str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        decoration = index.data(Qt.ItemDataRole.DecorationRole)
        icon = QIcon(decoration) if isinstance(decoration, QIcon) else QIcon()
        background = QStyleOptionViewItem(option)
        background.text, background.icon = "", QIcon()
        background.features &= ~(QStyleOptionViewItem.ViewItemFeature.HasDisplay |
                                 QStyleOptionViewItem.ViewItemFeature.HasDecoration)
        background.showDecorationSelected = True
        painter.save()
        painter.setClipRect(option.rect)
        view.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, background, painter, view)
        size = view.iconSize().width()
        if view.icons_above:
            icon_rect = QRect(option.rect.center().x() - size // 2, option.rect.top() + 4, size, size)
            text_rect = option.rect.adjusted(6, size + 10, -6, -4)
            alignment = Qt.AlignmentFlag.AlignHCenter
        else:
            icon_rect = QRect(option.rect.left() + 4, option.rect.center().y() - size // 2, size, size)
            text_rect = option.rect.adjusted(size + 10, 4, -6, -4)
            alignment = Qt.AlignmentFlag.AlignLeft
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        icon.paint(painter, icon_rect, Qt.AlignmentFlag.AlignCenter,
                   QIcon.Mode.Disabled if not enabled else QIcon.Mode.Selected if selected else QIcon.Mode.Normal)
        group = QPalette.ColorGroup.Disabled if not enabled else (
            QPalette.ColorGroup.Active if option.state & QStyle.StateFlag.State_Active else QPalette.ColorGroup.Inactive
        )
        role = QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text
        text_color = option.palette.color(group, role)
        painter.setPen(text_color)
        painter.setFont(option.font)
        layout, name_height = _name_layout(name, option.font, text_rect.width(), alignment)
        top = text_rect.top() if view.icons_above else text_rect.top() + max(0, (text_rect.height() - name_height) / 2)
        layout.draw(painter, QPointF(text_rect.left(), top))
        painter.restore()


class RemoteFileGrid(QListView):
    files_dropped = Signal(object, str)
    itemSelectionChanged = Signal()
    itemDoubleClicked = Signal(object, int)

    def __init__(self, tree, parent=None) -> None:
        super().__init__(parent)
        self._tree = tree
        self._mode = "list"
        self._layout_width = None
        self.icons_above = False
        self.setModel(tree.model())
        self.setModelColumn(0)
        self.setSelectionModel(tree.selectionModel())
        self._transfer_drag = _TransferDrag(self, REMOTE_FILES_MIME)
        self.setSelectionMode(QListView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QListView.SelectionBehavior.SelectItems)
        self.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setGridSize(QSize(220, 28))
        self.setIconSize(QSize(16, 16))
        self.setUniformItemSizes(True)
        self.setWordWrap(True)
        self.setMouseTracking(True)
        self.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setItemDelegate(_FileIconDelegate(self))
        self.selectionModel().selectionChanged.connect(lambda *_args: self.itemSelectionChanged.emit())
        self.doubleClicked.connect(lambda index: self.itemDoubleClicked.emit(tree.itemFromIndex(index), 0))

    def set_view_mode(self, mode: str) -> None:
        self._mode = mode
        _width, size, self.icons_above = _GRID_MODES[mode]
        self.setIconSize(QSize(size, size))
        self.refresh_layout(force=True)

    def refresh_layout(self, *, force: bool = False) -> None:
        preferred_width, size, _above = _GRID_MODES[self._mode]
        width = max(48, min(preferred_width, self.viewport().width()))
        if not force and self._layout_width == width:
            return
        self._layout_width = width
        text_width = max(1, width - (12 if self.icons_above else size + 16))
        metrics = self.fontMetrics()
        text_height = metrics.height()
        for row in range(self._tree.topLevelItemCount()):
            name = self._tree.topLevelItem(row).text(0)
            _layout, height = _name_layout(name, self.font(), text_width)
            text_height = max(text_height, height)
        height = size + text_height + 14 if self.icons_above else max(size, text_height) + 8
        self.setGridSize(QSize(width, math.ceil(height)))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.refresh_layout()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in {QEvent.Type.FontChange, QEvent.Type.StyleChange} and hasattr(self, "_mode"):
            self.refresh_layout(force=True)

    def itemAt(self, position):
        return self._tree.itemFromIndex(self.indexAt(position))

    def selectedItems(self):
        return self._tree.selectedItems()

    def setCurrentItem(self, item):
        self.setCurrentIndex(self._tree.indexFromItem(item))

    def scrollToItem(self, item):
        self.scrollTo(self._tree.indexFromItem(item))

    def configure_transfer(self, peer, paths, destination, context=None) -> None:
        self._transfer_drag.configure(peer, paths, destination, context)

    def set_transfer_state(self, enabled: bool, token: str) -> None:
        self._transfer_drag.set_state(enabled, token)

    def startDrag(self, _supported_actions) -> None:
        self._transfer_drag.start()

    def dragEnterEvent(self, event) -> None:
        self._transfer_drag.accept(event)

    def dragMoveEvent(self, event) -> None:
        self._transfer_drag.accept(event)

    def dropEvent(self, event) -> None:
        self._transfer_drag.drop(event)
