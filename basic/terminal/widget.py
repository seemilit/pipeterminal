"""Native terminal viewport with cell rendering, selection, IME and scrollback."""

import math

from PySide6.QtCore import QEvent, QPointF, QRect, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QCursor, QFont, QPainter
from PySide6.QtWidgets import QApplication, QAbstractScrollArea, QFrame, QMenu

from common.i18n import tr

from .engine import TerminalEngine
from .engine.api import TerminalEngineProtocol
from .input import encode_key
from .palettes import ShellPalette
from .renderer import Renderer
from .search import TerminalSearch
from .paths import reference_at


class NativeTerminalWidget(QAbstractScrollArea):
    textCommitted = Signal(str)
    binaryCommitted = Signal(bytes)
    terminalResized = Signal(int, int)
    metadataReceived = Signal(str, str)
    pathHovered = Signal(object)
    fileHovered = Signal(object)
    pathActivated = Signal(object)
    fileContextRequested = Signal(object, object)

    def __init__(self, parent=None, engine: TerminalEngineProtocol | None = None, paste_handler=None) -> None:
        super().__init__(parent)
        self.engine = engine or TerminalEngine()
        self._paste_handler = paste_handler
        self._selection = None
        self._dragging = False
        self._blink_on = True
        self._updating_scroll = False
        self._top_id = None
        self._observed_screen = self.engine.screen
        self._path_navigation_enabled = False
        self._hovered_path = None
        self._hovered_file = None
        self._color_theme: ShellPalette | None = None
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
        self.viewport().setMouseTracking(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        font = QFont("Cascadia Mono", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setFixedPitch(True)
        self.setFont(font)
        self.renderer = Renderer(font, self.palette())
        self.search = TerminalSearch(self)
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(500)
        self._blink_timer.timeout.connect(self._blink_cursor)
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(40)
        self._resize_timer.timeout.connect(self.fit)
        self.verticalScrollBar().valueChanged.connect(self._view_changed)
        self._selection_timer = QTimer(self)
        self._selection_timer.setInterval(40)
        self._selection_timer.timeout.connect(self._autoscroll_selection)
        self._drag_position = QPointF()
        QApplication.instance().installEventFilter(self)

    @Slot(object)
    def set_color_theme(self, theme: ShellPalette) -> None:
        if self._color_theme == theme:
            return
        self._color_theme = theme
        self.renderer = Renderer(self.font(), self.palette(), theme)
        self.verticalScrollBar().setStyleSheet(
            f"QScrollBar {{ background: {theme.background}; }}"
            f"QScrollBar::handle {{ background: {theme.scroll_thumb}; }}"
        )
        self.viewport().update()

    def enable_path_navigation(self, enabled: bool) -> None:
        self._path_navigation_enabled = enabled
        self._update_path_hover()

    def _set_path_hover(self, reference) -> None:
        if reference == self._hovered_path:
            return
        previous, self._hovered_path = self._hovered_path, reference
        first = self.verticalScrollBar().value()
        for path in (previous, reference):
            if path is not None:
                for identifier, start, end in path.spans:
                    index = self.engine.screen.index_of(identifier)
                    if index is not None and 0 <= index - first < self.engine.screen.rows:
                        self.viewport().update(self.renderer.cell_rect(index - first, start, end - start).toAlignedRect())
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if reference else Qt.CursorShape.IBeamCursor)
        self.pathHovered.emit(reference)

    def _set_file_hover(self, reference) -> None:
        if reference != self._hovered_file:
            self._hovered_file = reference
            self.fileHovered.emit(reference)

    def _update_path_hover(self, position=None, control=None) -> None:
        if position is None:
            position = self.viewport().mapFromGlobal(QCursor.pos())
        if control is None:
            control = QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier
        reference = None
        metrics = self.renderer.metrics
        inside = (
            metrics.padding <= position.x() < metrics.padding + self.engine.screen.cols * metrics.width
            and metrics.padding <= position.y() < metrics.padding + self.engine.screen.rows * metrics.height
            and self.viewport().rect().contains(position.toPoint() if isinstance(position, QPointF) else position)
        )
        if self._path_navigation_enabled and inside and not self._dragging and self.engine.path_links_enabled:
            reference = reference_at(self.engine.screen, *self._point_cell(position))
        self._set_file_hover(reference)
        self._set_path_hover(reference if control else None)

    def eventFilter(self, watched, event) -> bool:
        if event.type() in {QEvent.Type.KeyPress, QEvent.Type.KeyRelease} and event.key() == Qt.Key.Key_Control:
            self._update_path_hover(control=event.type() == QEvent.Type.KeyPress)
        elif event.type() == QEvent.Type.ApplicationDeactivate:
            self._set_path_hover(None)
            self._set_file_hover(None)
        return super().eventFilter(watched, event)

    def viewportEvent(self, event) -> bool:
        if event.type() == QEvent.Type.Leave and hasattr(self, "_hovered_path"):
            self._set_path_hover(None)
            self._set_file_hover(None)
        return super().viewportEvent(event)

    def feed(self, data: bytes) -> None:
        following = self.verticalScrollBar().value() == self.verticalScrollBar().maximum()
        self.engine.feed(data)
        if self._observed_screen is not self.engine.screen:
            self._observed_screen = self.engine.screen
            self._selection, self._top_id, following = None, None, True
        self._refresh(following)
        responses = self.engine.take_responses()
        if responses:
            self.binaryCommitted.emit(responses)
        for kind, data in self.engine.take_events():
            self.metadataReceived.emit(kind, data)
        self._update_path_hover()

    def write(self, text: str) -> None:
        self.feed(text.encode("utf-8"))

    def finish(self) -> None:
        self.engine.finish()
        self._refresh(self.verticalScrollBar().value() == self.verticalScrollBar().maximum())

    def clear(self) -> None:
        self._set_path_hover(None)
        self.engine.reset()
        self._observed_screen = self.engine.screen
        self._selection = self._top_id = None
        self._refresh(True)

    def _refresh(self, following: bool) -> None:
        screen = self.engine.screen
        if self._selection is not None and any(screen.index_of(point[0]) is None for point in self._selection):
            self._selection = None
        self._updating_scroll = True
        try:
            bar = self.verticalScrollBar()
            bar.setPageStep(screen.rows)
            bar.setRange(0, len(screen.history))
            index = screen.index_of(self._top_id) if self._top_id is not None else 0
            bar.setValue(bar.maximum() if following else min(bar.maximum(), index or 0))
            self._top_id = screen.row_at(bar.value()).id
        finally:
            self._updating_scroll = False
        damage = screen.take_damage()
        if damage.full:
            self.viewport().update()
        else:
            first = self.verticalScrollBar().value()
            for row in range(screen.rows):
                if screen.row_at(first + row).id in damage.line_ids:
                    rect = self.renderer.cell_rect(row, 0, screen.cols).toAlignedRect()
                    self.viewport().update(rect)
        self.search.invalidate()

    def fit(self) -> None:
        metrics = self.renderer.metrics
        rows = max(4, int((self.viewport().height() - 2 * metrics.padding) / metrics.height))
        cols = max(20, int((self.viewport().width() - 2 * metrics.padding) / metrics.width))
        if (rows, cols) != (self.engine.screen.rows, self.engine.screen.cols):
            self.engine.resize(rows, cols)
            self._refresh(self.verticalScrollBar().value() == self.verticalScrollBar().maximum())
            self.terminalResized.emit(cols, rows)
            self._update_path_hover()

    def terminal_size(self) -> tuple[int, int]:
        return self.engine.screen.cols, self.engine.screen.rows

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._resize_timer.start()

    def paintEvent(self, event) -> None:
        painter = QPainter(self.viewport())
        painter.fillRect(event.rect(), self.renderer.background)
        metrics = self.renderer.metrics
        first = self.verticalScrollBar().value()
        top = max(0, math.floor((event.rect().top() - metrics.padding) / metrics.height))
        bottom = min(self.engine.screen.rows, math.ceil((event.rect().bottom() - metrics.padding) / metrics.height) + 1)
        for row in range(top, bottom):
            line = self.engine.screen.row_at(first + row)
            self.renderer.paint_line(painter, line, row, self._selection, self.search.highlights.get(line.id, ()))
        if self._hovered_path is not None:
            painter.setPen(self.renderer.foreground)
            for identifier, start, end in self._hovered_path.spans:
                index = self.engine.screen.index_of(identifier)
                if index is not None and 0 <= index - first < self.engine.screen.rows:
                    rect = self.renderer.cell_rect(index - first, start, end - start)
                    painter.drawLine(QPointF(rect.left(), rect.bottom() - 2), QPointF(rect.right(), rect.bottom() - 2))
        rect = self._cursor_rect()
        if rect is not None and self._blink_on and self.engine.cursor.visible:
            if self.hasFocus():
                color = QColor(self.renderer.foreground)
                color.setAlpha(110)
                painter.fillRect(rect, color)
            else:
                painter.setPen(self.renderer.foreground)
                painter.drawRect(rect.adjusted(0, 0, -1, -1))
        painter.end()

    def _cursor_rect(self):
        row = len(self.engine.screen.history) + self.engine.cursor.row - self.verticalScrollBar().value()
        if 0 <= row < self.engine.screen.rows:
            return self.renderer.cell_rect(row, self.engine.cursor.col).toAlignedRect()
        return None

    def _blink_cursor(self) -> None:
        self._blink_on = not self._blink_on
        rect = self._cursor_rect()
        if rect is not None and self.engine.cursor.visible:
            self.viewport().update(rect)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self._blink_on = True
        self._blink_timer.start()
        rect = self._cursor_rect()
        if rect is not None:
            self.viewport().update(rect)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self._blink_timer.stop()
        self._blink_on = True
        rect = self._cursor_rect()
        if rect is not None:
            self.viewport().update(rect)

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.KeyPress and event.key() in {Qt.Key.Key_Tab, Qt.Key.Key_Backtab}:
            self.keyPressEvent(event)
            return True
        return super().event(event)

    def keyPressEvent(self, event) -> None:
        control = event.modifiers() & Qt.KeyboardModifier.ControlModifier
        shift = event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        if control and event.key() == Qt.Key.Key_C and (shift or self.has_selection()):
            self.copy()
        elif control and event.key() == Qt.Key.Key_V:
            self.paste_clipboard()
        elif shift and event.key() in {Qt.Key.Key_PageUp, Qt.Key.Key_PageDown}:
            direction = -1 if event.key() == Qt.Key.Key_PageUp else 1
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() + direction * self.engine.screen.rows)
        else:
            data = encode_key(event.key(), event.text(), event.modifiers(), self.engine.application_cursor)
            if data:
                self._selection = None
                self.scroll_to_bottom()
                self.binaryCommitted.emit(data)
        event.accept()

    def inputMethodEvent(self, event) -> None:
        if event.commitString():
            self.binaryCommitted.emit(event.commitString().encode("utf-8"))
        event.accept()

    def inputMethodQuery(self, query):
        if query == Qt.InputMethodQuery.ImCursorRectangle:
            return self._cursor_rect() or QRect()
        return super().inputMethodQuery(query)

    def _point_cell(self, position) -> tuple[int, int]:
        metrics = self.renderer.metrics
        row = max(0, min(self.engine.screen.rows - 1, int((position.y() - metrics.padding) / metrics.height)))
        line = self.engine.screen.row_at(self.verticalScrollBar().value() + row)
        col = max(0, min(len(line.cells) - 1, int((position.x() - metrics.padding) / metrics.width)))
        if line.cells[col].continuation:
            col -= 1
        return line.id, col

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._update_path_hover(event.position(), event.modifiers() & Qt.KeyboardModifier.ControlModifier)
            if self._hovered_path is not None:
                self.pathActivated.emit(self._hovered_path)
                event.accept()
                return
            self.setFocus()
            cell = self._point_cell(event.position())
            self._selection = (cell, cell)
            self._dragging = True
            self._drag_position = event.position()
            self._selection_timer.start()
            self.viewport().update()
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        self._update_path_hover(event.position(), event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if self._dragging:
            self._drag_position = event.position()
            self._selection = (self._selection[0], self._point_cell(event.position()))
            self.viewport().update()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._dragging = False
        self._selection_timer.stop()
        self._update_path_hover(event.position(), event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        event.accept()

    def _autoscroll_selection(self) -> None:
        if self._drag_position.y() < 0 or self._drag_position.y() > self.viewport().height():
            direction = -1 if self._drag_position.y() < 0 else 1
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() + direction)
            self._selection = (self._selection[0], self._point_cell(self._drag_position))
            self.viewport().update()

    def selected_text(self) -> str:
        return self.engine.screen.selected_text(*self._selection) if self._selection else ""

    def has_selection(self) -> bool:
        return bool(self.selected_text())

    def copy(self) -> None:
        text = self.selected_text()
        if text:
            QApplication.clipboard().setText(text)

    def paste(self, text: str) -> None:
        data = text.encode("utf-8")
        if self.engine.bracketed_paste:
            data = b"\x1b[200~" + data + b"\x1b[201~"
        self.binaryCommitted.emit(data)

    def paste_clipboard(self) -> None:
        if self._paste_handler is not None and self._paste_handler():
            return
        text = QApplication.clipboard().text()
        if text:
            self.paste(text)

    def contextMenuEvent(self, event) -> None:
        if self.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu:
            self.customContextMenuRequested.emit(self.viewport().mapTo(self, event.pos()))
            return
        if self._path_navigation_enabled and self.engine.path_links_enabled and self.viewport().rect().contains(event.pos()):
            reference = reference_at(self.engine.screen, *self._point_cell(event.pos()))
            if reference is not None:
                self.fileContextRequested.emit(reference, event.globalPos())
                event.accept()
                return
        self.show_text_context_menu(event.globalPos())

    def show_text_context_menu(self, position) -> None:
        menu = QMenu(self)
        copy_action = menu.addAction(tr("复制"))
        copy_action.setEnabled(self.has_selection())
        copy_action.triggered.connect(self.copy)
        menu.addAction(tr("粘贴")).triggered.connect(self.paste_clipboard)
        try:
            menu.exec(position)
        finally:
            menu.deleteLater()

    def scroll_to_bottom(self) -> None:
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def focus_terminal(self) -> None:
        self.setFocus()

    def _view_changed(self, _value: int) -> None:
        if not self._updating_scroll:
            self._top_id = self.engine.screen.row_at(self.verticalScrollBar().value()).id
            self.viewport().update()
            self._update_path_hover()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        if not self._updating_scroll:
            self.viewport().update()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in {QEvent.Type.PaletteChange, QEvent.Type.FontChange} and hasattr(self, "renderer"):
            self.renderer = Renderer(self.font(), self.palette(), self._color_theme)
            self.engine.screen.invalidate()
            self.fit()
            self.viewport().update()

    def shutdown(self) -> None:
        self.search.shutdown()
        QApplication.instance().removeEventFilter(self)
        self._set_path_hover(None)
        self._set_file_hover(None)
        self._blink_timer.stop()
        self._resize_timer.stop()
        self._selection_timer.stop()
