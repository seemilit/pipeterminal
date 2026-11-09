"""Single-file three-way editor backed by a shared conflict session."""

from threading import Thread
from bisect import bisect_right
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut, QTextCursor, QTextFormat
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QMenu, QMessageBox, QSplitter, QTextEdit, QVBoxLayout, QWidget
from common.i18n import tr
from common.i18n.widgets import QDialog, QLabel, QPushButton
from .conflict_diff import ConflictDiff
from .merge_display import AlignedCodeEdit, aligned_rows
from .merge_visuals import CodeHighlighter, ConnectionLane, DifferenceOverview, MergeActionButton


def _units(text):
    return len(text.encode("utf-16-le")) // 2


class MergeEditor(QDialog, ConflictDiff):
    changed = Signal()
    mapping_ready = Signal(int, object)
    suggestion_ready = Signal(int, int, object)
    applied = Signal(str, bool)
    navigation_requested = Signal(str, int)

    def __init__(self, session, path, parent=None):
        super().__init__(parent)
        self.session = session
        self.path = path
        self.draft = session.files[path]
        self._loading = False
        self._scrolling = False
        self._mapping_busy = False
        self._revision = 0
        self._mapping_revision = -1
        self._maps = {}
        self._decorations = [[], [], []]
        self._buttons = []
        self._actions = {}
        self._suggest_busy = False
        self._highlighters = []
        self._pending_view = None
        self._navigate_first = True
        self._pending_navigation = None
        self._coordinate_revision = -1
        self._coordinates = {}
        self.setWindowTitle(tr("手动合并") + " — " + path)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint | Qt.WindowType.WindowMinimizeButtonHint)
        self.resize(1400, 820)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._refresh_visuals)
        self.mapping_ready.connect(self._mapped)
        self.suggestion_ready.connect(self._show_suggestion)
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        for label, symbol, shortcut, handler in (("上一处冲突", "up", "Shift+F7", lambda: self._navigate(-1)), ("下一处冲突", "down", "F7", lambda: self._navigate(1)), ("撤销", "undo", "Ctrl+Z", lambda: self._history(-1)), ("重做", "redo", "", lambda: self._history(1))):
            button = MergeActionButton(symbol, self)
            button.setAccessibleName(str(tr(label)))
            button.setToolTip(str(tr(label)) + (" (" + shortcut + ")" if shortcut else ""))
            button.clicked.connect(lambda _checked=False, action=handler: action())
            toolbar.addWidget(button)
            self._actions[label] = button
        self.highlight_mode = QComboBox()
        self.highlight_mode.addItem(str(tr("按词高亮")), "word")
        self.highlight_mode.addItem(str(tr("按行高亮")), "line")
        self.highlight_mode.currentIndexChanged.connect(self._display_changed)
        toolbar.addWidget(self.highlight_mode)
        self.ignore_space = QCheckBox(str(tr("忽略空白差异")))
        self.ignore_space.toggled.connect(self._display_changed)
        toolbar.addWidget(self.ignore_space)
        toolbar.addStretch()
        self.status = QLabel()
        toolbar.addWidget(self.status)
        layout.addLayout(toolbar)
        self.notice = QLabel(tr("二进制或特殊文件，请选择保留的一侧"))
        self.notice.setVisible(not self.draft.item["text"])
        layout.addWidget(self.notice)
        self.panes = QSplitter(Qt.Orientation.Horizontal)
        self.panes.setChildrenCollapsible(False)
        self.editors = []
        self.lanes = []
        request = session.request
        for index, title in enumerate((tr("目标版本：{0}", request["left"]), tr("合并结果"), tr("来源版本：{0}", request["right"]))):
            if index:
                lane = ConnectionLane()
                self.lanes.append(lane)
                self.panes.addWidget(lane)
            panel = QWidget()
            column = QVBoxLayout(panel)
            column.setContentsMargins(0, 0, 0, 0)
            column.addWidget(QLabel(title))
            editor = AlignedCodeEdit(index != 1 or not self.draft.item["text"])
            editor.geometry_changed.connect(self._update_inline)
            editor.verticalScrollBar().valueChanged.connect(lambda value, source=editor: self._scroll(source, value))
            self.editors.append(editor)
            self._highlighters.append(CodeHighlighter(editor.document(), path, editor.palette()))
            column.addWidget(editor)
            self.panes.addWidget(panel)
            self.panes.setStretchFactor(index * 2, 1)
        self.panes.setSizes([420, 48, 420, 48, 420])
        self.left, self.result, self.right = self.editors
        self.overview = DifferenceOverview(self.result)
        self.overview.setToolTip(str(tr("点击定位差异")))
        content = QHBoxLayout()
        content.addWidget(self.panes, 1)
        content.addWidget(self.overview)
        layout.addLayout(content, 1)
        self.result.textChanged.connect(self._edited)
        self.result.cursorPositionChanged.connect(self._status)
        self.result.undo_requested.connect(lambda: self._history(-1))
        self.result.redo_requested.connect(lambda: self._history(1))
        self.result.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.result.customContextMenuRequested.connect(self._menu)
        footer = QHBoxLayout()
        footer.addWidget(QLabel(tr("无冲突修改已自动应用")))
        self.next_file = QCheckBox(str(tr("应用后打开下一文件")))
        footer.addWidget(self.next_file)
        suggest = QPushButton(tr("简单冲突建议"))
        suggest.clicked.connect(self._suggest)
        self._actions["简单冲突建议"] = suggest
        footer.addWidget(suggest)
        footer.addStretch()
        for label, choice in (("此块先左后右", "both"), ("此块先右后左", "reverse"), ("标记此块已解决", "manual")):
            button = QPushButton(tr(label)) if choice == "manual" else MergeActionButton(choice, self)
            button.setAccessibleName(str(tr(label)))
            button.setToolTip(str(tr(label)))
            button.clicked.connect(lambda _checked=False, action=choice: self._change(self._current_block(), action))
            footer.addWidget(button)
            self._actions[label] = button
        apply = QPushButton(tr("应用结果"))
        self.apply_button = apply
        apply.clicked.connect(self._apply)
        close = QPushButton(tr("关闭"))
        close.clicked.connect(self.hide)
        footer.addWidget(apply)
        footer.addWidget(close)
        layout.addLayout(footer)
        for key, callback in (("F7", lambda: self._navigate(1)), ("Shift+F7", lambda: self._navigate(-1)), ("Ctrl+Return", self._apply)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(callback)
        self.reload()

    def _capture_view(self):
        cursor = self.result.cursorForPosition(self.result.viewport().rect().topLeft())
        block_cursor = QTextCursor(cursor.block())
        return (cursor.blockNumber(), self.result.cursorRect(block_cursor).top(), [editor.horizontalScrollBar().value() for editor in self.editors])

    def _restore_view(self, view):
        line, y, horizontal = view
        block = self.result.document().findBlockByNumber(min(line, self.result.document().blockCount() - 1))
        value = self.result.verticalScrollBar().value() + self.result.cursorRect(QTextCursor(block)).top() - y
        for editor, x in zip(self.editors, horizontal):
            editor.verticalScrollBar().setValue(value)
            editor.horizontalScrollBar().setValue(x)

    def reload(self):
        self._pending_view = self._capture_view()
        old_cursor = self.result.textCursor()
        position, anchor = old_cursor.position(), old_cursor.anchor()
        self._loading = True
        item = self.draft.item
        for editor, stage in ((self.left, 2), (self.right, 3)):
            content = item["stages"].get(stage)
            editor.setPlainText(content.get("text", str(tr("二进制或特殊文件，请选择保留的一侧"))) if content else str(tr("此侧文件不存在")))
        self.result.setPlainText(self.draft.text)
        cursor = self.result.textCursor()
        end = self.result.document().characterCount() - 1
        cursor.setPosition(min(anchor, end))
        cursor.setPosition(min(position, end), QTextCursor.MoveMode.KeepAnchor)
        self.result.setTextCursor(cursor)
        self._loading = False
        self._revision += 1
        self._status()
        self._refresh_visuals()

    def _edited(self):
        if self._loading or self.result.formatting:
            return
        text = self.result.toPlainText()
        if text == self.draft.text:
            return
        self.draft.edit(text)
        self._revision += 1
        self._status()
        self._highlight()
        self._timer.start()
        self.changed.emit()

    def _status(self):
        if self._loading or not hasattr(self, "apply_button"):
            return
        self.status.setText(tr("剩余冲突：{0}", self.draft.remaining))
        self._actions["撤销"].setEnabled(self.draft.history_index > 0)
        self._actions["重做"].setEnabled(self.draft.history_index + 1 < len(self.draft.history))
        navigable = any(draft.item["text"] and draft.remaining > 0 for draft in self.session.files.values())
        for label in ("上一处冲突", "下一处冲突"):
            self._actions[label].setEnabled(navigable)
        index = self._current_block()
        for label in ("此块先左后右", "此块先右后左", "标记此块已解决"):
            self._actions[label].setEnabled(index is not None and (label == "标记此块已解决" or self.draft.can_choose(index)))
        self._actions["简单冲突建议"].setEnabled(index is not None and not self._suggest_busy and self.draft.can_choose(index))
        self.apply_button.setEnabled(self.draft.remaining == 0)
        self.apply_button.setToolTip("" if self.draft.remaining == 0 else str(tr("请处理冲突，手动编辑后需标记已解决")))

    def _display_changed(self, *_args):
        self._revision += 1
        self._timer.start()

    def _refresh_visuals(self):
        self._highlight()
        if self._mapping_busy or self._mapping_revision == self._revision or not self.draft.item["text"]:
            return
        texts = [editor.toPlainText().split("\n") for editor in self.editors]
        base = self.draft.item["stages"].get(1, {}).get("text", "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
        self._mapping_busy = True
        Thread(target=self._build_maps, args=(self._revision, texts, base, self.highlight_mode.currentData(), self.ignore_space.isChecked()), daemon=True).start()

    def _mapped(self, revision, payload):
        self._mapping_busy = False
        if revision != self._revision:
            self._timer.start()
            return
        self._maps, self._decorations = payload
        self._mapping_revision = revision
        texts = [editor.toPlainText().split("\n") for editor in self.editors]
        _rows, numbers = aligned_rows(texts, self._maps)
        # Block margins affect only geometry, not copied or saved text.
        self._scrolling = True
        view = self._pending_view or self._capture_view()
        self._pending_view = None
        try:
            for editor, lines in zip(self.editors, numbers):
                editor.align_rows(lines)
            self._restore_view(view)
        finally:
            self._scrolling = False
        self._highlight()
        if self._pending_navigation is not None:
            direction = self._pending_navigation
            self._pending_navigation = None
            self._focus_edge(direction)
        elif self._navigate_first:
            self._navigate_first = False
            self._navigate(0)

    def _highlight(self):
        if not hasattr(self, "result"):
            return
        for pane, editor in enumerate(self.editors):
            selections = self._selections(editor, self._decorations[pane])
            if pane == 1:
                for block in self.draft.blocks:
                    if block.state not in {"unresolved", "edited"}:
                        continue
                    cursor = QTextCursor(editor.document())
                    cursor.setPosition(self._coordinate(block.start)[0])
                    cursor.setPosition(self._coordinate(block.end)[0], QTextCursor.MoveMode.KeepAnchor)
                    selection = QTextEdit.ExtraSelection()
                    selection.cursor = cursor
                    selection.format.setBackground(QColor(230, 80, 80, 65))
                    selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
                    selections.append(selection)
            if pane != 1 and self._mapping_revision == self._revision:
                highlights = []
                for block in self.draft.blocks:
                    if block.state not in {"unresolved", "edited"}:
                        continue
                    start = self._coordinate(block.start)[1]
                    end = self._coordinate(max(block.start, block.end - 1))[1]
                    first, last = self._side_line(pane, start), self._side_line(pane, end)
                    highlights.extend((line, None, None, "conflict") for line in range(first, max(first, last) + 1))
                selections.extend(self._selections(editor, highlights))
            editor.setExtraSelections(selections)
        colors = {"insert": "#45a568", "delete": "#d35e5e", "replace": "#538dd1"}
        markers = {(line, colors[color]) for line, _start, _end, color in self._decorations[1] if color in colors}
        markers.update((self._coordinate(block.start)[1], "#de6947") for block in self.draft.blocks if block.state in {"unresolved", "edited"})
        self.overview.markers = sorted(markers)
        self.overview.update()
        self._update_inline()

    def _side_line(self, side, line):
        starts, entries = self._maps.get((1, side), ([], []))
        if not entries:
            return line
        a0, a1, b0, b1 = entries[max(0, min(len(entries) - 1, bisect_right(starts, line) - 1))]
        return b0 + min(max(0, b1 - b0 - 1), max(0, line - a0))

    def _scroll(self, source, value):
        if self._scrolling or self._loading:
            return
        self._scrolling = True
        try:
            for editor in self.editors:
                if editor is not source:
                    editor.verticalScrollBar().setValue(value)
        finally:
            self._scrolling = False
        self._update_inline()

    def _coordinate(self, offset):
        if self._coordinate_revision != self._revision:
            points = sorted({point for block in self.draft.blocks for point in (block.start, block.end, max(block.start, block.end - 1))})
            self._coordinates = {}
            previous = units = line = 0
            for point in points:
                fragment = self.draft.text[previous:point]
                units += _units(fragment)
                line += fragment.count("\n")
                self._coordinates[point] = (units, line)
                previous = point
            self._coordinate_revision = self._revision
        return self._coordinates[offset]

    def _current_block(self):
        position = self.result.textCursor().position()
        return next((index for index, block in enumerate(self.draft.blocks) if self._coordinate(block.start)[0] <= position < self._coordinate(block.end)[0] or self._coordinate(block.start)[0] == self._coordinate(block.end)[0] == position), None)

    def focus_edge(self, direction):
        """Position after alignment so a late background result cannot reset the view."""
        self._navigate_first = False
        if self._mapping_revision != self._revision:
            self._pending_navigation = direction
            self._refresh_visuals()
        else:
            self._focus_edge(direction)

    def _focus_edge(self, direction):
        blocks = [block for block in self.draft.blocks if block.state in {"unresolved", "edited"}]
        if not blocks:
            return
        self._focus_block(blocks[0] if direction > 0 else blocks[-1])

    def _focus_block(self, block):
        cursor = self.result.textCursor()
        cursor.setPosition(self._coordinate(block.start)[0])
        self.result.setTextCursor(cursor)
        self.result.ensureCursorVisible()
        self.result.setFocus()

    def _navigate(self, direction):
        if direction == 0:
            self._focus_edge(1)
            return
        blocks = [block for block in self.draft.blocks if block.state in {"unresolved", "edited"}]
        position = self.result.textCursor().position()
        current = self._current_block()
        if current is not None:
            position = self._coordinate(self.draft.blocks[current].start)[0]
        candidates = [block for block in blocks if (self._coordinate(block.start)[0] > position if direction > 0 else self._coordinate(block.start)[0] < position)]
        if candidates:
            self._focus_block(candidates[0] if direction > 0 else candidates[-1])
        else:
            self.navigation_requested.emit(self.path, direction)

    def _change(self, index, action, side=None):
        if index is None or not 0 <= index < len(self.draft.blocks):
            return
        if action != "manual" and not self.draft.can_choose(index):
            return
        self._pending_view = self._capture_view()
        position = self.result.verticalScrollBar().value()
        if action == "accept":
            self.draft.accept_side(index, side)
        elif action == "ignore":
            self.draft.ignore(index, side)
        elif action == "manual":
            self.draft.mark_manual(index)
        else:
            self.draft.choose(index, action)
        self._loading = True
        self.result.setPlainText(self.draft.text)
        cursor = self.result.textCursor()
        cursor.setPosition(_units(self.draft.text[:self.draft.blocks[index].start]))
        self.result.setTextCursor(cursor)
        self.result.verticalScrollBar().setValue(position)
        self._loading = False
        self._revision += 1
        self._status()
        self._refresh_visuals()
        self.changed.emit()

    def _update_inline(self):
        if not hasattr(self, "result"):
            return
        for button in self._buttons:
            button.hide()
        for lane in self.lanes:
            lane.bands = []
            lane.update()
        if self._loading or not self.draft.item["text"] or (self.draft.resolution and self.draft.resolution[0] != "text"):
            return
        used = 0
        last_y = -25
        for index, block in enumerate(self.draft.blocks):
            cursor = QTextCursor(self.result.document())
            cursor.setPosition(self._coordinate(block.start)[0])
            rect = self.result.cursorRect(cursor)
            if rect.top() < 0 or rect.top() > self.result.viewport().height() - 22 or rect.top() - last_y < 22:
                continue
            last_y = rect.top()
            if self._mapping_revision == self._revision:
                end_cursor = QTextCursor(self.result.document())
                end_cursor.setPosition(self._coordinate(max(block.start, block.end - 1))[0])
                end_rect = self.result.cursorRect(end_cursor)
                color = QColor(230, 80, 80, 45) if block.state in {"unresolved", "edited"} else QColor(60, 170, 100, 40)
                for lane, pane in zip(self.lanes, (0, 2)):
                    side_editor = self.editors[pane]
                    first = self._side_line(pane, self._coordinate(block.start)[1])
                    last = self._side_line(pane, self._coordinate(max(block.start, block.end - 1))[1])
                    first = max(0, min(first, side_editor.document().blockCount() - 1))
                    last = max(first, min(last, side_editor.document().blockCount() - 1))
                    side_top = side_editor.cursorRect(QTextCursor(side_editor.document().findBlockByNumber(first)))
                    side_bottom = side_editor.cursorRect(QTextCursor(side_editor.document().findBlockByNumber(last)))
                    ys = (lane.mapFromGlobal(side_editor.viewport().mapToGlobal(side_top.topLeft())).y(), lane.mapFromGlobal(side_editor.viewport().mapToGlobal(side_bottom.bottomLeft())).y())
                    ym = (lane.mapFromGlobal(self.result.viewport().mapToGlobal(rect.topLeft())).y(), lane.mapFromGlobal(self.result.viewport().mapToGlobal(end_rect.bottomLeft())).y())
                    lane.bands.append((*ys, *ym, color) if pane == 0 else (*ym, *ys, color))
            for lane, side, arrow in zip(self.lanes, ("left", "right"), ("right", "left")):
                controls = (("ignore", "ignore", "忽略此侧"), (arrow, "accept", "采用此侧")) if side == "left" else ((arrow, "accept", "采用此侧"), ("ignore", "ignore", "忽略此侧"))
                for column, (symbol, action, label) in enumerate(controls):
                    if used == len(self._buttons):
                        button = MergeActionButton(symbol, lane)
                        button.clicked.connect(lambda _checked=False, control=button: self._change(control.property("block"), control.property("action"), control.property("side")))
                        self._buttons.append(button)
                    button = self._buttons[used]
                    if button.parentWidget() is not lane:
                        button.setParent(lane)
                    button.setSymbol(symbol)
                    version = tr("目标版本：{0}", self.session.request["left"]) if side == "left" else tr("来源版本：{0}", self.session.request["right"])
                    description = str(tr(label)) + "\n" + str(version)
                    button.setToolTip(description)
                    button.setAccessibleName(description)
                    button.setEnabled(self.draft.can_choose(index) and side not in (block.accepted if action == "accept" else block.ignored))
                    button.setProperty("block", index)
                    button.setProperty("action", action)
                    button.setProperty("side", side)
                    point = lane.mapFromGlobal(self.result.viewport().mapToGlobal(rect.topLeft()))
                    button.setFixedSize(24, 22)
                    button.move(column * 24, point.y())
                    button.show()
                    used += 1

    def _history(self, direction):
        if self.draft.restore(direction):
            self.reload()
            self.changed.emit()

    def _menu(self, point):
        cursor = self.result.cursorForPosition(point)
        if not self.result.textCursor().hasSelection():
            self.result.setTextCursor(cursor)
        index = self._current_block()
        menu = QMenu(self)
        for label, callback, enabled in (("撤销", lambda: self._history(-1), self.draft.history_index > 0), ("重做", lambda: self._history(1), self.draft.history_index + 1 < len(self.draft.history)), ("复制", self.result.copy, self.result.textCursor().hasSelection()), ("粘贴", self.result.paste, not self.result.isReadOnly())):
            action = menu.addAction(str(tr(label)))
            action.setEnabled(enabled)
            action.triggered.connect(lambda _checked=False, handler=callback: handler())
        menu.addSeparator()
        for label, choice in (("此块采用左侧", "left"), ("此块采用右侧", "right"), ("此块先左后右", "both"), ("此块先右后左", "reverse"), ("标记此块已解决", "manual")):
            action = menu.addAction(str(tr(label)))
            action.setEnabled(index is not None and (choice == "manual" or self.draft.can_choose(index)))
            action.triggered.connect(lambda _checked=False, value=choice: self._change(index, value))
        menu.exec(self.result.viewport().mapToGlobal(point))
        menu.deleteLater()

    def _suggest(self):
        index = self._current_block()
        if index is None or self._suggest_busy or not self.draft.can_choose(index):
            return
        block = self.draft.blocks[index]
        self._suggest_busy = True
        self._status()
        revision = self._revision
        values = (block.base, block.left, block.right)
        def calculate():
            from .merge_assist import simple_merge
            try:
                result = simple_merge(*values)
            except Exception:
                result = None
            try:
                self.suggestion_ready.emit(revision, index, result)
            except RuntimeError:
                pass
        Thread(target=calculate, daemon=True).start()

    def _show_suggestion(self, revision, index, value):
        self._suggest_busy = False
        self._status()
        if revision != self._revision:
            return
        if value is None:
            QMessageBox.information(self, tr("简单冲突建议"), tr("改动相互重叠或过于复杂，请手动处理"))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("确认合并建议"))
        dialog.resize(850, 600)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(tr("请检查建议内容，确认后才会采用")))
        preview = AlignedCodeEdit(True)
        preview.setPlainText(value)
        highlighter = CodeHighlighter(preview.document(), self.path, preview.palette())
        layout.addWidget(preview)
        buttons = QHBoxLayout()
        confirm = QPushButton(tr("确认"))
        confirm.clicked.connect(dialog.accept)
        cancel = QPushButton(tr("取消"))
        cancel.clicked.connect(dialog.reject)
        buttons.addStretch()
        buttons.addWidget(confirm)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        dialog.deleteLater()
        if accepted and revision == self._revision:
            block = self.draft.blocks[index]
            self.draft.replace(block.start, block.end, value, selected=block)
            block.state = "manual"
            block.accepted.clear()
            block.ignored.clear()
            self.draft.record()
            self.reload()
            self.changed.emit()

    def _apply(self):
        if not self.draft.apply():
            message = "仍有未解决的冲突" if self.draft.item["text"] else "二进制或特殊文件，请选择保留的一侧"
            QMessageBox.warning(self, tr("解决冲突"), tr(message))
            return
        self.changed.emit()
        self.hide()
        if self.parentWidget():
            self.parentWidget().show()
            self.parentWidget().raise_()
        self.applied.emit(self.path, self.next_file.isChecked())

    def reject(self):
        self.hide()

    def closeEvent(self, event):
        self.hide()
        event.ignore()
