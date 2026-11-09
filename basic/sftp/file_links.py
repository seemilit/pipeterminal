"""Ctrl-hover file links; navigation is delegated to the owning Shell."""

from PySide6.QtCore import QEvent, QPersistentModelIndex, Qt
from PySide6.QtGui import QCursor, QFont
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem
from shiboken6 import isValid

from .model import RemoteEntry


def underline_file_link(option, index, view):
    hovered = getattr(view, "_file_link_index", None)
    if index.column() == 0 and hovered is not None and hovered.isValid() and hovered == index:
        font = QFont(option.font)
        font.setUnderline(True)
        option.font = font


class FileLinkDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        option = QStyleOptionViewItem(option)
        self.initStyleOption(option, index)
        view = self.parent()
        view.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, option, painter, view)

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        underline_file_link(option, index, self.parent())


class FileLinkHover:
    def __init__(self, browser):
        self.browser = browser
        self.allowed = None
        self._view = self._index = self._pressed = None

    def _enabled(self):
        return self.allowed is not None and self.allowed() and self.browser._connected

    def _views(self):
        views = [self.browser.tree]
        directory_tree = self.browser.directory_tree
        if directory_tree is not None:
            views.append(directory_tree.tree)
        return views

    def _entry(self, index):
        value = index.data(Qt.ItemDataRole.UserRole)
        if isinstance(value, str) and value.startswith("/"):
            return RemoteEntry(value.rsplit("/", 1)[-1] or "/", value, True, False, 0, 0)
        return value if isinstance(value, RemoteEntry) else None

    def clear(self):
        self._set_hover(None, None)
        self._pressed = None

    def _set_hover(self, view, index):
        if view is self._view and index == self._index:
            return
        previous, previous_index = self._view, self._index
        self._view = view
        self._index = QPersistentModelIndex(index) if index is not None else None
        if previous is not None and isValid(previous):
            previous._file_link_index = None
            previous.viewport().unsetCursor()
            if previous_index is not None and previous_index.isValid():
                previous_item = previous_index.model().index(previous_index.row(), previous_index.column(), previous_index.parent())
                previous.viewport().update(previous.visualRect(previous_item))
        if view is not None:
            view._file_link_index = self._index
            view.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
            view.viewport().update(view.visualRect(index))

    def _hover(self, view, position, control):
        index = view.indexAt(position)
        if control and self._enabled() and view.isEnabled() and index.isValid():
            index = index.siblingAtColumn(0)
            entry = self._entry(index)
            if entry is not None:
                self._set_hover(view, index)
                return entry
        self._set_hover(None, None)
        return None

    def event_filter(self, watched, event):
        kind = event.type()
        if kind == QEvent.Type.ApplicationDeactivate:
            self.clear()
        elif kind in {QEvent.Type.KeyPress, QEvent.Type.KeyRelease} and event.key() == Qt.Key.Key_Control:
            for view in self._views():
                position = view.viewport().mapFromGlobal(QCursor.pos())
                if view.isVisible() and view.viewport().rect().contains(position):
                    self._hover(view, position, kind == QEvent.Type.KeyPress)
                    break
            else:
                self.clear()
        elif kind in {
            QEvent.Type.Leave, QEvent.Type.Hide, QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick, QEvent.Type.MouseButtonRelease,
        }:
            view = next((value for value in self._views() if watched is value.viewport() or watched is value), None)
            if view is None:
                return False
            if kind in {QEvent.Type.Leave, QEvent.Type.Hide}:
                if view is self._view:
                    self.clear()
            elif kind == QEvent.Type.MouseMove:
                position = event.position().toPoint()
                if watched is view:
                    position = view.viewport().mapFrom(view, position)
                self._hover(view, position, event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            elif kind in {QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick, QEvent.Type.MouseButtonRelease} and event.button() == Qt.MouseButton.LeftButton:
                position = event.position().toPoint()
                if watched is view:
                    position = view.viewport().mapFrom(view, position)
                entry = self._hover(view, position, event.modifiers() & Qt.KeyboardModifier.ControlModifier)
                pressed = self._pressed
                if kind == QEvent.Type.MouseButtonRelease:
                    self._pressed = None
                    if pressed is not None:
                        event.accept()
                        return True
                elif entry is not None:
                    if kind == QEvent.Type.MouseButtonPress:
                        self.browser.shell_entry_requested.emit(entry)
                    self._pressed = (view, entry.path)
                    event.accept()
                    return True
        return False
