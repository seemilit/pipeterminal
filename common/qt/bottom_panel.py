"""Bottom panel coordinating independent, resizable groups of feature tabs."""

from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QApplication, QFrame, QMenu, QRubberBand, QSplitter, QVBoxLayout, QWidget

from .module_page import ModulePage
from .panel_group import PanelTabGroup
from .panel_tab_bar import PANEL_MIME, PanelTabBar

from common.i18n import tr


class BottomPanel(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("bottomPanel")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumHeight(160)
        self._panels: dict[str, QWidget] = {}
        self._focused = False
        self._groups: list[PanelTabGroup] = []
        self._active_group = None
        self.setAcceptDrops(True)
        self._drop_preview = QRubberBand(QRubberBand.Shape.Rectangle, self)
        self._drop_preview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(6)
        layout.addWidget(self.splitter, 1)
        self._create_group()
        QApplication.instance().focusChanged.connect(self._track_focus)

    @property
    def tabs(self) -> PanelTabGroup:
        return self._active_group

    def _create_group(self) -> PanelTabGroup:
        group = PanelTabGroup()
        self._groups.append(group)
        self.splitter.addWidget(group)
        self.splitter.setStretchFactor(self.splitter.indexOf(group), 1)
        group.activated.connect(lambda target=group: self._activate_group(target))
        group.new_panel_requested.connect(self._request_new_panel)
        group.context_menu_requested.connect(self._show_tab_menu)
        if self._active_group is None:
            self._active_group = group
        return group

    def _group_for_panel(self, panel: QWidget) -> PanelTabGroup | None:
        return next((group for group in self._groups if group.indexOf(panel) >= 0), None)

    def _panel_drop_target(self, event):
        bar = event.source()
        if not isinstance(bar, PanelTabBar) or not event.mimeData().hasFormat(PANEL_MIME):
            return None
        panel = bar.dragged_panel
        source = self._group_for_panel(panel)
        if source is None or not event.possibleActions() & Qt.DropAction.MoveAction:
            return None
        point = event.position().toPoint()
        for group in self._groups:
            if not group.isVisible():
                continue
            rect = QRect(group.mapTo(self, group.rect().topLeft()), group.size())
            if rect.contains(point):
                tab_bar = group.tabBar()
                tab_rect = QRect(tab_bar.mapTo(self, tab_bar.rect().topLeft()), tab_bar.size())
                side = "center" if tab_rect.contains(point) else "left" if point.x() < rect.left() + rect.width() // 2 else "right"
                if source is group and (side == "center" or source.panel_count() < 2):
                    return None
                return panel, group, side, rect
        return None

    def dragEnterEvent(self, event):
        bar = event.source()
        if (isinstance(bar, PanelTabBar) and event.mimeData().hasFormat(PANEL_MIME)
                and self._group_for_panel(bar.dragged_panel) is not None
                and event.possibleActions() & Qt.DropAction.MoveAction):
            self.dragMoveEvent(event)
            # Keep receiving movement even if the drag starts over its own pane.
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        target = self._panel_drop_target(event)
        if target is None:
            self._drop_preview.hide()
            event.ignore()
            return
        _panel, _group, side, rect = target
        if side == "left":
            rect.setWidth(rect.width() // 2)
        elif side == "right":
            rect.setLeft(rect.left() + rect.width() // 2)
        self._drop_preview.setGeometry(rect)
        self._drop_preview.show()
        self._drop_preview.raise_()
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()

    def dragLeaveEvent(self, event):
        self._drop_preview.hide()
        event.accept()

    def dropEvent(self, event):
        self._drop_preview.hide()
        target = self._panel_drop_target(event)
        if target is None:
            event.ignore()
            return
        panel, group, side, _rect = target
        if side == "center":
            self._move_panel(panel, group)
        else:
            index = self._groups.index(group) + (side == "right")
            new_group = self._create_group()
            self._groups.remove(new_group)
            self._groups.insert(index, new_group)
            self.splitter.insertWidget(index, new_group)
            self._move_panel(panel, new_group)
            self.splitter.setSizes([max(1, self.splitter.width() // len(self._groups))] * len(self._groups))
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()

    def _activate_group(self, group: PanelTabGroup) -> None:
        if group not in self._groups:
            return
        self._active_group = group
        panel = group.currentWidget()
        if self._focused and isinstance(panel, ModulePage):
            panel.set_panel_focus(True)

    def _track_focus(self, _old, current) -> None:
        if current is not None:
            for group in self._groups:
                if current is group or group.isAncestorOf(current):
                    self._active_group = group
                    break

    def _request_new_panel(self, panel: QWidget) -> None:
        group = self._group_for_panel(panel)
        if group is not None and isinstance(panel, ModulePage):
            self._active_group = group
            panel.new_panel_requested.emit()

    def add_panel(self, panel_id: str, name: str, panel: QWidget) -> None:
        if panel_id in self._panels:
            raise ValueError(tr("面板已存在：{0}", panel_id))
        self._panels[panel_id] = panel
        self.tabs.add_panel(name, panel)
        if isinstance(panel, ModulePage):
            panel.set_panel_focus(self._focused)
        panel.windowTitleChanged.connect(self._update_panel_title)

    def _update_panel_title(self, title: str) -> None:
        panel = self.sender()
        group = self._group_for_panel(panel)
        if group is not None:
            group.setTabText(group.indexOf(panel), title)

    def has_panel(self, panel_id: str) -> bool:
        return panel_id in self._panels

    def panel_id(self, panel: QWidget) -> str | None:
        return next((panel_id for panel_id, target in self._panels.items() if target is panel), None)

    def set_panel_focus(self, focused: bool) -> None:
        self._focused = focused
        for panel in self._panels.values():
            if isinstance(panel, ModulePage):
                panel.set_panel_focus(focused)

    def has_panels(self) -> bool:
        return bool(self._panels)

    def remove_panel(self, panel_id: str) -> None:
        panel = self._panels.pop(panel_id, None)
        if panel is None:
            return
        panel.windowTitleChanged.disconnect(self._update_panel_title)
        group = self._group_for_panel(panel)
        if group is not None:
            group.take_panel(panel)
            panel.setParent(self)
            self._remove_empty_groups()

    def show_panel(self, panel_id: str) -> None:
        panel = self._panels[panel_id]
        group = self._group_for_panel(panel)
        if group is not None:
            self._active_group = group
            group.setCurrentWidget(panel)
            group.show()

    def _show_tab_menu(self, panel: QWidget, position) -> None:
        group = self._group_for_panel(panel)
        if group is None:
            return
        menu = QMenu(self)
        duplicate = menu.addAction(tr("复制"))
        duplicate.setEnabled(isinstance(panel, ModulePage) and panel.can_duplicate_panel())
        duplicate.triggered.connect(lambda _checked=False: self._duplicate_panel(panel))
        disconnect = menu.addAction(tr("断开"))
        disconnect.setEnabled(isinstance(panel, ModulePage) and panel.can_disconnect_panel())
        disconnect.triggered.connect(lambda _checked=False: panel.disconnect_panel())
        menu.addSeparator()
        split = menu.addAction(tr("新建并排面板"))
        split.setEnabled(isinstance(panel, ModulePage) and panel.can_duplicate_panel())
        split.triggered.connect(lambda _checked=False: self._split_new_panel(panel))
        move = menu.addAction(tr("移到新分栏"))
        move.setEnabled(group.panel_count() > 1)
        move.triggered.connect(lambda _checked=False: self._move_to_new_group(panel))
        for index, target in enumerate(self._groups, 1):
            if target is not group:
                action = menu.addAction(tr("移到分栏 {0}", index))
                action.triggered.connect(lambda _checked=False, target=target: self._move_panel(panel, target))
        menu.addSeparator()
        index = group.indexOf(panel)
        left = tuple(group.widget(position) for position in range(index) if group.isTabEnabled(position))
        right = tuple(group.widget(position) for position in range(index + 1, group.count()) if group.isTabEnabled(position))
        others = tuple(target for target in self._panels.values() if target is not panel)
        for label, targets in (
            ("关闭", (panel,)), ("关闭其他", others),
            ("关闭全部", tuple(self._panels.values())), ("关闭左侧", left), ("关闭右侧", right),
        ):
            action = menu.addAction(tr(label))
            action.setEnabled(any(isinstance(target, ModulePage) for target in targets))
            action.triggered.connect(lambda _checked=False, targets=targets: self._close_panels(targets))
        try:
            menu.exec(position)
        finally:
            menu.deleteLater()

    def _close_panels(self, panels) -> None:
        identifiers = [self.panel_id(panel) for panel in panels]
        for panel_id in identifiers:
            panel = self._panels.get(panel_id)
            if isinstance(panel, ModulePage):
                panel.close_requested.emit()
                if panel_id in self._panels:
                    break

    def _duplicate_panel(self, panel: QWidget) -> QWidget | None:
        group = self._group_for_panel(panel)
        if group is None or not isinstance(panel, ModulePage) or not panel.can_duplicate_panel():
            return None
        self._active_group = group
        group.setCurrentWidget(panel)
        previous = set(self._panels)
        panel.duplicate_panel_requested.emit()
        created = [target for panel_id, target in self._panels.items() if panel_id not in previous]
        return created[-1] if created else None

    def _split_new_panel(self, panel: QWidget) -> None:
        created = self._duplicate_panel(panel)
        if created is not None:
            self._move_to_new_group(created)

    def _move_to_new_group(self, panel: QWidget) -> None:
        source = self._group_for_panel(panel)
        if source is None or source.panel_count() < 2:
            return
        target = self._create_group()
        self._move_panel(panel, target)
        self.splitter.setSizes([max(1, self.splitter.width() // len(self._groups))] * len(self._groups))

    def _move_panel(self, panel: QWidget, target: PanelTabGroup) -> None:
        source = self._group_for_panel(panel)
        if source is None or source is target or target not in self._groups:
            return
        name = source.tabText(source.indexOf(panel))
        source.take_panel(panel)
        target.add_panel(name, panel)
        self._active_group = target
        target.setCurrentWidget(panel)
        self._remove_empty_groups()

    def _remove_empty_groups(self) -> None:
        for group in tuple(self._groups):
            if group.panel_count() == 0:
                group.hide()
                if len(self._groups) > 1:
                    index = self._groups.index(group)
                    self._groups.remove(group)
                    if self._active_group is group:
                        self._active_group = self._groups[max(0, index - 1)]
                    group.setParent(None)
                    group.deleteLater()
