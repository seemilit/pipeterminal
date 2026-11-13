"""Task flow diagram and localized parameter summary."""

from collections import defaultdict

from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QRectF, QSize, QSignalBlocker, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QDrag, QKeySequence, QIcon, QPixmap, QPainter, QPainterPath, QPainterPathStroker, QPalette, QPen, QPolygonF
from PySide6.QtWidgets import QAbstractItemView, QGraphicsItem, QGraphicsRectItem, QGraphicsPathItem, QGraphicsScene, QGraphicsView, QApplication, QStyle, QTreeWidget, QWidget, QMenu

from common.i18n import tr
from common.i18n.widgets import QTreeWidgetItem

from .git.schema import POLICIES
from .graph import START
from .schema import FIELD_LABELS, STEP_LABELS, CATEGORIES
from .execution.schema import STEP_LABELS as EXECUTION_LABELS, CHOICES
from .upload import STEP_LABELS as UPLOAD_LABELS, POLICIES as UPLOAD_POLICIES


class _FlowNode(QGraphicsRectItem):
    PORTS = {"left": QPointF(-9, 40), "right": QPointF(309, 40), "top": QPointF(150, -9), "bottom": QPointF(150, 89)}
    DIRECTIONS = {"left": QPointF(-1, 0), "right": QPointF(1, 0), "top": QPointF(0, -1), "bottom": QPointF(0, 1)}

    def port_at(self, point):
        nearest = min(self.PORTS, key=lambda name: (point - self.PORTS[name]).manhattanLength())
        return nearest if (point - self.PORTS[nearest]).manhattanLength() <= 14 else None

    def anchor(self, port):
        return self.pos() + self.PORTS[port] - self.DIRECTIONS[port] * 6

    def _arrow_center(self, port):
        return self.PORTS[port] + self.DIRECTIONS[port] * 21

    def add_direction_at(self, point):
        if self.quick_add_enabled:
            for port in self.PORTS:
                offset = point - self._arrow_center(port)
                if abs(offset.x()) <= 9 and abs(offset.y()) <= 9:
                    return port
        return None

    def boundingRect(self):
        return self.rect().adjusted(-40, -40, 40, 40)

    def shape(self):
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.WindingFill)
        path.addRoundedRect(self.rect(), 9, 9)
        for port, point in self.PORTS.items():
            path.addEllipse(point, 10, 10)
            if self.quick_add_enabled:
                track = QRectF(point, self._arrow_center(port)).normalized()
                path.addRect(track.adjusted(-9, -9, 9, 9))
        return path

    def hoverEnterEvent(self, event):
        self.setZValue(1)
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setZValue(0)
        self.update()
        super().hoverLeaveEvent(event)

    def __init__(self, title, subtitle, palette):
        super().__init__(0, 0, 300, 80)
        self._title, self._subtitle, self._palette = title, subtitle, palette
        self.state = ""
        self.error = ""
        self.badge = "Git"
        self.quick_add_enabled = False
        self.link_highlights = 0
        self.link_target = False
        self.setAcceptHoverEvents(True)
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setToolTip(f"{title}\n{subtitle}")

    def paint(self, painter, option, widget=None):
        palette = self._palette
        selected = self.isSelected()
        highlighted = selected or self.link_target or self.link_highlights > 0 or self.isUnderMouse()
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        shadow = QColor(0, 0, 0, 22)
        painter.setBrush(shadow)
        painter.drawRoundedRect(self.rect().translated(0, 3), 9, 9)
        border = QColor("#ef4444") if self.error else palette.color(QPalette.ColorRole.Highlight if highlighted else QPalette.ColorRole.Mid)
        painter.setPen(QPen(border, 2 if selected or self.error else 1))
        painter.setBrush(palette.brush(QPalette.ColorRole.Base))
        painter.drawRoundedRect(self.rect(), 9, 9)
        accent = palette.color(QPalette.ColorRole.Highlight)
        tint = QColor(accent)
        tint.setAlpha(25)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(tint)
        painter.drawRoundedRect(18, 22, 36, 36, 7, 7)
        painter.setPen(accent)
        painter.drawText(18, 22, 36, 36, Qt.AlignmentFlag.AlignCenter, self.badge)
        painter.setPen(palette.color(QPalette.ColorRole.Text))
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        title = painter.fontMetrics().elidedText(self._title, Qt.TextElideMode.ElideRight, 210)
        painter.drawText(self.rect().adjusted(66, 10, -18, -38), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(palette.color(QPalette.ColorRole.PlaceholderText))
        subtitle = painter.fontMetrics().elidedText(self._subtitle, Qt.TextElideMode.ElideRight, 210)
        painter.drawText(self.rect().adjusted(66, 40, -18, -12), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, subtitle)
        colors = {"waiting": "#94a3b8", "running": "#3b82f6", "success": "#22c55e", "failed": "#ef4444"}
        if self.state:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(colors[self.state]))
            painter.drawEllipse(280, 8, 10, 10)
        painter.setPen(QPen(palette.color(QPalette.ColorRole.Highlight), 1.5))
        painter.setBrush(palette.brush(QPalette.ColorRole.Base))
        if self.isUnderMouse():
            for point in self.PORTS.values():
                painter.drawEllipse(point, 5, 5)
            if self.quick_add_enabled:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(accent)
                for port, direction in self.DIRECTIONS.items():
                    center = self._arrow_center(port)
                    side = QPointF(-direction.y(), direction.x())
                    painter.drawPolygon(QPolygonF([
                        center + direction * 6,
                        center - direction * 4 + side * 5,
                        center - direction * 4 - side * 5,
                    ]))
        painter.restore()


class _FlowEdge(QGraphicsPathItem):
    def __init__(self, path, first, second, pen, editable):
        super().__init__(path)
        self.endpoints = (first, second)
        self.editable = editable
        self.hovered = False
        self.setPen(pen)
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.insert_point = path.pointAtPercent(path.percentAtLength(path.length() / 2))
        self.setToolTip(tr("点击＋插入节点；选中连线后按 Delete 删除"))

    def boundingRect(self):
        return super().boundingRect().adjusted(-11, -11, 11, 11)

    def shape(self):
        stroke = QPainterPathStroker()
        stroke.setWidth(12)
        shape = stroke.createStroke(self.path())
        shape.setFillRule(Qt.FillRule.WindingFill)
        if self.editable and (self.hovered or self.isSelected()):
            shape.addEllipse(self.insert_point, 10, 10)
        return shape

    def _set_hovered(self, hovered):
        if self.hovered == hovered:
            return
        self.hovered = hovered
        for node in self.endpoints:
            node.link_highlights += 1 if hovered else -1
            node.update()
        self.update()

    def hoverEnterEvent(self, event):
        self._set_hovered(True)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._set_hovered(False)
        super().hoverLeaveEvent(event)

    def paint(self, painter, option, widget=None):
        active = self.hovered or self.isSelected()
        pen = self.pen()
        if active:
            color = pen.color()
            color.setAlpha(255)
            pen.setColor(color)
            pen.setWidthF(2.5)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self.path())
        if active and self.editable:
            point = self.insert_point
            painter.setBrush(self.endpoints[0]._palette.brush(QPalette.ColorRole.Base))
            painter.drawEllipse(point, 9, 9)
            painter.drawLine(point - QPointF(4, 0), point + QPointF(4, 0))
            painter.drawLine(point - QPointF(0, 4), point + QPointF(0, 4))


class TaskFlowView(QGraphicsView):
    step_selected = Signal(int)
    step_activated = Signal()
    module_dropped = Signal(str, int)
    module_add_requested = Signal(int, str, str)
    position_changed = Signal(int, object)
    connection_requested = Signal(int, int, str, str)
    node_copy_requested = Signal(int)
    node_delete_requested = Signal(object)
    run_from_requested = Signal(int)
    run_only_requested = Signal(object)
    edge_delete_requested = Signal(object)
    edge_insert_requested = Signal(object, str)
    undo_requested = Signal()
    redo_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.scene().selectionChanged.connect(self._selected)
        self._nodes = []
        self._start_node = None
        self._link_nodes = {}
        self._links = ()
        self._add_arrow_press = None
        self._selection_press = False
        self._editable = False
        self._press_pos = QPoint()
        self._drag_index = None
        self._edges = []
        self._guides = []
        self._link_source = None
        self._link_preview = None
        self._link_port = None
        self._link_target = None
        self.connection_allowed = None
        self.parallel_enabled = False
        self._drag_origin = None
        self.drop_position = None
        self._states = {}
        self._invalid = {}
        self._auto_center = True
        self._center_timer = QTimer(self)
        self._center_timer.setSingleShot(True)
        self._center_timer.timeout.connect(self._center_flow_now)
        self.horizontalScrollBar().sliderPressed.connect(self._stop_auto_center)
        self.verticalScrollBar().sliderPressed.connect(self._stop_auto_center)
        self.setAcceptDrops(True)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

    def drawBackground(self, painter, rect):
        painter.fillRect(rect, self.palette().brush(QPalette.ColorRole.AlternateBase))
        color = self.palette().color(QPalette.ColorRole.Mid)
        color.setAlpha(100)
        pen = QPen(color, 1.5)
        pen.setCosmetic(True)
        painter.setPen(pen)
        spacing = 24 if self.transform().m11() >= 0.7 else 48
        left, top = int(rect.left() // spacing) * spacing, int(rect.top() // spacing) * spacing
        for x in range(left, int(rect.right()) + 1, spacing):
            for y in range(top, int(rect.bottom()) + 1, spacing):
                painter.drawPoint(QPointF(x, y))

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._nodes and self._start_node is None:
            painter = QPainter(self.viewport())
            painter.setPen(self.palette().color(QPalette.ColorRole.PlaceholderText))
            painter.drawText(
                self.viewport().rect().adjusted(20, 20, -20, -20),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                str(tr("从左侧拖入模块添加流程")),
            )
            painter.end()
    def display_steps(self, steps, selected=None, *, graph=None):
        center = self.mapToScene(self.viewport().rect().center())
        blocker = QSignalBlocker(self.scene())
        self._edges.clear()
        self._guides.clear()
        self._link_preview = None
        self._link_source = None
        self._link_target = None
        self._drag_index = None
        self._add_arrow_press = None
        self.scene().clear()
        self._nodes.clear()
        self._start_node = None
        self._link_nodes.clear()
        self._links = graph["links"] if graph is not None else ()
        palette = self.palette()
        self.setBackgroundBrush(palette.brush(QPalette.ColorRole.Base))
        if graph is not None:
            node = _FlowNode(str(tr("开始")), "", palette)
            node.badge = "▶"
            node.quick_add_enabled = self._editable
            node.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
            node.setData(0, -1)
            self.scene().addItem(node)
            self._start_node = self._link_nodes[START] = node
        for index, step in enumerate(steps):
            y = 20 + index * 116
            label = STEP_LABELS.get(step["type"], step["type"])
            properties = step.get("properties", {})
            source = properties.get("SOURCE_BRANCH") or tr("当前分支")
            target = properties.get("TARGET_BRANCH") or tr("当前分支")
            subtitle = f"{source} → {target}" if step["type"] == "MERGE_BRANCH" else properties.get("WORKING_DIRECTORY", "") if step["type"] in EXECUTION_LABELS else properties.get("PROJECT_PATH", "")
            if step["type"] in EXECUTION_LABELS:
                mode = properties.get("EXECUTION_MODE", "script" if step["type"].endswith("SCRIPT") else "command")
                subtitle = str(tr("脚本" if mode == "script" else "命令")) + (" · " + str(subtitle) if subtitle else "")
            if step["type"] in UPLOAD_LABELS:
                subtitle = properties.get("SERVER", "") + " · " + properties.get("UPLOAD_DIRECTORY", "")
            if step["type"] in {"HEALTH_CHECK", "OPEN_SHELL"}:
                subtitle = properties.get("SERVER", "")
            if step["type"] == "WAIT":
                subtitle = str(tr("等待 {0} 秒", properties.get("SECONDS", "1")))
            node = _FlowNode(
                str(tr("{0}. {1}", index + 1, tr(label))),
                str(subtitle), palette,
            )
            position = step.get("position", [20, y])
            if not isinstance(position, (list, tuple)) or len(position) != 2 or not all(isinstance(v, (int, float)) and -1000000 <= v <= 1000000 for v in position):
                position = [20, y]
            node.badge = ">_" if step["type"].startswith("LOCAL") else "SSH" if step["type"].startswith("REMOTE") else "↑" if step["type"] in UPLOAD_LABELS else "Mvn" if step["type"] == "MAVEN_BUILD" else "Ⅱ" if step["type"] == "WAIT" else "✓" if step["type"] == "HEALTH_CHECK" else ">_" if step["type"] == "OPEN_SHELL" else "Git"
            node.setPos(*position)
            node.setData(0, index)
            node.quick_add_enabled = self._editable
            if graph is not None:
                self._link_nodes[step["node_id"]] = node
            node.error = self._invalid.get(index, "")
            if node.error:
                node.setToolTip(node.toolTip() + "\n" + node.error)
            self.scene().addItem(node)
            self._nodes.append(node)
            if index in self._states:
                self.set_step_state(index, self._states[index])
        if self._start_node is not None:
            first = self._nodes[0].pos() if self._nodes else QPointF(20, 20)
            self._start_node.setPos(*graph.get("start_position", [first.x(), first.y() - 152 if self._nodes else first.y()]))
        self._draw_edges()
        self._expand_canvas(center)
        if selected is not None and 0 <= selected < len(self._nodes):
            self._nodes[selected].setSelected(True)
        del blocker
        if self._auto_center:
            self._center_timer.start(0)

    def _stop_auto_center(self):
        self._auto_center = False
        self._center_timer.stop()

    def center_flow(self):
        self._auto_center = True
        self._center_timer.start(0)

    def _center_flow_now(self):
        if not self._auto_center:
            return
        height = self.viewport().height()
        top_gap = min(64, max(24, height * 0.14))
        scale = self.transform().m22()
        first_node = self._start_node or (self._nodes[0] if self._nodes else None)
        if first_node is not None:
            first = first_node.mapRectToScene(first_node.rect())
            center = QPointF(first.center().x(), first.top() + (height / 2 - top_gap) / scale)
        else:
            center = QPointF(170, 20 + (height / 2 - top_gap) / scale)
        self._expand_canvas(center)

    def _expand_canvas(self, center=None):
        center = center if center is not None else self.mapToScene(self.viewport().rect().center())
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        margin = max(1000, visible.width(), visible.height())
        bounds = self.scene().itemsBoundingRect().united(visible)
        self.scene().setSceneRect(bounds.adjusted(-margin, -margin, margin, margin))
        self.centerOn(center)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_nodes"):
            self._expand_canvas()
            if self._auto_center:
                self._center_timer.start(0)

    def set_editable(self, editable):
        self._editable = editable
        if not editable:
            self._set_link_target(None)
            if self._link_preview is not None:
                self.scene().removeItem(self._link_preview)
                self._link_preview = None
            self._link_source = None
            self._drag_index = None
            self._add_arrow_press = None
        for edge in self._edges:
            edge.editable = editable
            edge.update()
        for node in self._link_nodes.values():
            if node.quick_add_enabled != editable:
                node.quick_add_enabled = editable
                node.update()

    def _node_at_index(self, index):
        return self._start_node if index == -1 else self._nodes[index]

    def next_module_position(self, index, direction):
        node = self._node_at_index(index)
        vector = node.DIRECTIONS[direction]
        distance = node.rect().width() if vector.x() else node.rect().height()
        offset = vector * (distance + 80)
        point = node.pos() + offset
        occupied = [item.rect().translated(item.pos()).adjusted(-24, -24, 24, 24) for item in self._link_nodes.values()]
        while any(node.rect().translated(point).intersects(rect) for rect in occupied):
            point += offset
        return [point.x(), point.y()]

    def edge_output_port(self, endpoints):
        return next(edge.data(1) for edge in self._edges if edge.data(0) == endpoints)

    def insertion_position(self, endpoints, source_index, direction):
        edge = next(edge for edge in self._edges if edge.data(0) == endpoints)
        first, second = edge.endpoints
        point = (first.pos() + second.pos()) / 2
        proposed = first.rect().translated(point).adjusted(-24, -24, 24, 24)
        if any(proposed.intersects(node.rect().translated(node.pos())) for node in self._link_nodes.values()):
            side = "right" if direction in {"top", "bottom"} else "bottom"
            return self.next_module_position(source_index, side)
        return [point.x(), point.y()]

    def clear_states(self, waiting_indexes=()):
        self._states = {index: "waiting" for index in waiting_indexes}
        for index, node in enumerate(self._nodes):
            node.state = self._states.get(index, "")
            node.setToolTip(f"{node._title}\n{node._subtitle}")
            if index in self._states:
                self.set_step_state(index, "waiting")
            node.update()

    def set_step_state(self, index, state):
        self._states[index] = state
        if 0 <= index < len(self._nodes):
            self._nodes[index].state = state
            labels = {"waiting": "等待执行", "running": "正在执行", "success": "执行成功", "failed": "执行失败"}
            node = self._nodes[index]
            node.setToolTip(f"{node._title}\n{node._subtitle}\n{tr(labels[state])}")
            self._nodes[index].update()

    def wheelEvent(self, event):
        self._stop_auto_center()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if not event.angleDelta().y():
                event.accept()
                return
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            if 0.4 <= self.transform().m11() * factor <= 2.5:
                self.scale(factor, factor)
                self._expand_canvas()
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._selection_press = False
            self._stop_auto_center()
            self._expand_canvas()
        self._press_pos = event.position().toPoint()
        item = self.itemAt(self._press_pos)
        self._drag_index = None
        self._add_arrow_press = None
        if self._editable and isinstance(item, _FlowEdge) and event.button() == Qt.MouseButton.LeftButton:
            self._selection_press = True
            self.setFocus()
            endpoints = item.data(0)
            insert = (item.hovered or item.isSelected()) and (item.insert_point - self.mapToScene(self._press_pos)).manhattanLength() <= 12
            blocker = QSignalBlocker(self.scene())
            self.scene().clearSelection()
            item.setSelected(True)
            del blocker
            self.step_selected.emit(-1)
            if insert:
                self._open_add_menu(event.globalPosition().toPoint(), endpoints=endpoints)
            event.accept()
            return
        if isinstance(item, _FlowNode):
            if event.button() == Qt.MouseButton.RightButton:
                event.accept()
                return
            if event.button() == Qt.MouseButton.LeftButton:
                if item.data(0) >= 0 and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    self._selection_press = True
                    self.setFocus()
                    blocker = QSignalBlocker(self.scene())
                    for edge in self._edges:
                        if edge.isSelected():
                            edge.setSelected(False)
                    item.setSelected(not item.isSelected())
                    del blocker
                    if item.isSelected():
                        self.step_selected.emit(item.data(0))
                    else:
                        self._selected()
                    event.accept()
                    return
                local = item.mapFromScene(self.mapToScene(self._press_pos))
                direction = item.add_direction_at(local)
                if direction is not None:
                    self._add_arrow_press = (item.data(0), direction)
                    event.accept()
                    return
                self._drag_index = item.data(0)
        if self._drag_index is not None:
            self._drag_origin = QPointF(item.pos())
            local = item.mapFromScene(self.mapToScene(self._press_pos))
            port = item.port_at(local)
            if self._editable and port is not None:
                self._link_port = port
                self._link_source = self._drag_index
                self._link_preview = self.scene().addPath(QPainterPath(), self._connection_pen(preview=True))
                self._link_preview.setZValue(-1)
                event.accept()
                return
        if event.button() == Qt.MouseButton.LeftButton:
            blocker = QSignalBlocker(self.scene())
            super().mousePressEvent(event)
            self.scene().clearSelection()
            if self._drag_index is not None:
                item.setSelected(True)
            del blocker
            self.step_selected.emit(self._drag_index if self._drag_index is not None else -1)
        else:
            super().mousePressEvent(event)

    def _draw_edges(self):
        selected = {edge.data(0) for edge in self._edges if edge.isSelected()}
        for edge in self._edges:
            edge._set_hovered(False)
            self.scene().removeItem(edge)
        self._edges.clear()
        routes = []
        ports = defaultdict(list)
        for source, target, output_port, input_port in self._links:
            first, second = self._link_nodes[source], self._link_nodes[target]
            delta = second.pos() - first.pos()
            if abs(delta.x()) / 300 > abs(delta.y()) / 80:
                output, incoming = ("right", "left") if delta.x() >= 0 else ("left", "right")
            else:
                output, incoming = ("bottom", "top") if delta.y() >= 0 else ("top", "bottom")
            output = output_port or output
            incoming = input_port or incoming
            index = len(routes)
            routes.append((source, target, first, second, output, incoming))
            ports[source, output].append((index, 0, second))
            ports[target, incoming].append((index, 1, first))
        offsets = {}
        for (node_id, port), members in ports.items():
            node = self._link_nodes[node_id]
            horizontal = bool(node.DIRECTIONS[port].x())
            members.sort(key=lambda member: member[2].y() if horizontal else member[2].x())
            span = node.rect().height() if horizontal else node.rect().width()
            spacing = min(14, (span - 32) / max(1, len(members) - 1))
            tangent = QPointF(0, 1) if horizontal else QPointF(1, 0)
            for slot, (index, side, _) in enumerate(members):
                offsets[index, side] = tangent * ((slot - (len(members) - 1) / 2) * spacing)
        cards = tuple(node.rect().translated(node.pos()) for node in self._link_nodes.values())
        for index, (source, target, first, second, output, incoming) in enumerate(routes):
            start = first.anchor(output) + offsets[index, 0]
            end = second.anchor(incoming) + offsets[index, 1]
            offset = offsets[index, 0] if not offsets[index, 0].isNull() else offsets[index, 1]
            path = self._connection_path(start, end, output, incoming, cards, offset.x() + offset.y())
            edge = _FlowEdge(path, first, second, self._connection_pen(), self._editable)
            self.scene().addItem(edge)
            edge.setData(0, (source, target))
            edge.setData(1, output)
            edge.setZValue(-1)
            if (source, target) in selected:
                edge.setSelected(True)
            self._edges.append(edge)

    def _connection_pen(self, *, preview=False):
        color = self.palette().color(QPalette.ColorRole.Highlight)
        color.setAlpha(155 if preview else 210)
        pen = QPen(color, 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return pen

    @classmethod
    def _connection_path(cls, start, end, output, incoming, cards=(), lane=0):
        departure = _FlowNode.DIRECTIONS[output]
        arrival = _FlowNode.DIRECTIONS[incoming]
        points = cls._connection_points(start, end, departure, arrival, cards, lane)
        path = QPainterPath(start)
        for previous, corner, following in zip(points, points[1:], points[2:]):
            before, after = previous - corner, following - corner
            if QPointF.dotProduct(before, after) != 0:
                path.lineTo(corner)
                continue
            radius = min(7, before.manhattanLength() / 2, after.manhattanLength() / 2)
            path.lineTo(corner + before * (radius / before.manhattanLength()))
            path.quadTo(corner, corner + after * (radius / after.manhattanLength()))
        path.lineTo(end)
        perpendicular = QPointF(-arrival.y(), arrival.x())
        arrow_base = end + arrival * 8
        path.moveTo(arrow_base + perpendicular * 4)
        path.lineTo(end)
        path.lineTo(arrow_base - perpendicular * 4)
        return path

    @classmethod
    def _connection_points(cls, start, end, departure, arrival, cards, lane=0):
        lead = 16
        gap = QPointF.dotProduct(end - start, departure)
        if departure == -arrival and gap > 0:
            lead = min(lead, gap / 2)
        first, last = start + departure * lead, end + arrival * lead
        left = min(first.x(), last.x(), *(card.left() for card in cards)) - 16
        right = max(first.x(), last.x(), *(card.right() for card in cards)) + 16
        top = min(first.y(), last.y(), *(card.top() for card in cards)) - 16
        bottom = max(first.y(), last.y(), *(card.bottom() for card in cards)) + 16
        middle_x = (first.x() + last.x()) / 2
        middle_y = (first.y() + last.y()) / 2
        if departure.x():
            middle_x += max(-abs(first.x() - last.x()) / 4, min(lane, abs(first.x() - last.x()) / 4))
        else:
            middle_y += max(-abs(first.y() - last.y()) / 4, min(lane, abs(first.y() - last.y()) / 4))

        # Prefer a centered step when opposing ports are offset.
        routes = [
            (QPointF(x, first.y()), QPointF(x, last.y()))
            for x in (middle_x, left, right)
        ] + [
            (QPointF(first.x(), y), QPointF(last.x(), y))
            for y in (middle_y, top, bottom)
        ] + [(QPointF(first.x(), last.y()),), (QPointF(last.x(), first.y()),)]
        obstacles = tuple(card.adjusted(-2, -2, 2, 2) for card in cards)
        candidates = []
        for bends in routes:
            points, reversals = cls._compact_route((start, first, *bends, last, end))
            segments = tuple(zip(points, points[1:]))
            crossings = sum(cls._segment_crosses_card(a, b, card) for a, b in segments for card in obstacles)
            length = sum((b - a).manhattanLength() for a, b in segments)
            candidates.append(((crossings, reversals, len(points), length), points))
        return min(candidates, key=lambda candidate: candidate[0])[1]

    @staticmethod
    def _compact_route(route):
        points = [route[0]]
        reversals = 0
        for point in route[1:]:
            if point == points[-1]:
                continue
            if len(points) > 1:
                before, after = points[-1] - points[-2], point - points[-1]
                direction = QPointF.dotProduct(before, after)
                if direction > 0:
                    points[-1] = point
                    continue
                if direction < 0:
                    reversals += 1
            points.append(point)
        return points, reversals

    @staticmethod
    def _segment_crosses_card(start, end, card):
        if start.x() == end.x():
            top, bottom = sorted((start.y(), end.y()))
            return card.left() < start.x() < card.right() and top < card.bottom() and bottom > card.top()
        left, right = sorted((start.x(), end.x()))
        return card.top() < start.y() < card.bottom() and left < card.right() and right > card.left()

    def layout_positions(self):
        return [[node.x(), node.y()] for node in self._nodes]

    def set_validation_issues(self, issues):
        self._invalid = {}
        for index, message in issues:
            if index >= 0:
                self._invalid[index] = self._invalid.get(index, "") + message + "\n"
        for index, node in enumerate(self._nodes):
            node.error = self._invalid.get(index, "")
            node.setToolTip(f"{node._title}\n{node._subtitle}\n{node.error}".strip())
            node.update()

    def contextMenuEvent(self, event):
        if not self._editable:
            return
        item = self.itemAt(event.pos())
        if isinstance(item, _FlowNode):
            index = item.data(0)
            if index < 0:
                event.accept()
                return
            if not item.isSelected():
                self.select_step(index, reveal=False)
                self.step_selected.emit(index)
            selected = self.selected_step_indexes()
            menu = QMenu(self)
            remove = menu.addAction(str(tr("删除节点")))
            menu.addSeparator()
            run_from = menu.addAction(str(tr("从此节点开始执行")))
            run_one = menu.addAction(str(tr("执行此节点")))
            run_selected = menu.addAction(str(tr("仅执行选中节点")))
            run_selected.setEnabled(len(selected) > 1)
            try:
                action = menu.exec(event.globalPos())
                if action is remove:
                    self.node_delete_requested.emit((index,))
                elif action is run_from:
                    self.run_from_requested.emit(index)
                elif action is run_one:
                    self.run_only_requested.emit((index,))
                elif action is run_selected:
                    self.run_only_requested.emit(selected)
            finally:
                menu.deleteLater()
        elif item in self._edges:
            index = item.data(0)
            menu = QMenu(self)
            try:
                insert = menu.addAction(str(tr("插入节点")))
                action = menu.addAction(str(tr("删除连线")))
                chosen = menu.exec(event.globalPos())
                if chosen is insert:
                    self._open_add_menu(event.globalPos(), endpoints=index)
                elif chosen is action:
                    self.edge_delete_requested.emit(index)
            finally:
                menu.deleteLater()
        event.accept()

    def keyPressEvent(self, event):
        if self._editable and event.key() == Qt.Key.Key_Delete and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            indexes = self.selected_step_indexes()
            if indexes and not event.isAutoRepeat():
                self.node_delete_requested.emit(indexes)
            elif not event.isAutoRepeat():
                edge = next((edge for edge in self._edges if edge.isSelected()), None)
                if edge is not None:
                    self.edge_delete_requested.emit(edge.data(0))
            event.accept()
            return
        if self._editable and event.matches(QKeySequence.StandardKey.Undo):
            self.undo_requested.emit()
            event.accept()
            return
        if self._editable and event.matches(QKeySequence.StandardKey.Redo):
            self.redo_requested.emit()
            event.accept()
            return
        if self._editable and event.matches(QKeySequence.StandardKey.Copy):
            nodes = [item for item in self.scene().selectedItems() if isinstance(item, _FlowNode)]
            if nodes:
                self.node_copy_requested.emit(nodes[0].data(0))
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape and self._link_source is not None:
            self._set_link_target(None)
            self.scene().removeItem(self._link_preview)
            self._link_preview = None
            self._link_source = None
            self._drag_index = None
            event.accept()
            return
        super().keyPressEvent(event)

    def _clear_guides(self):
        for guide in self._guides:
            self.scene().removeItem(guide)
        self._guides.clear()

    def _snap_position(self, node, position):
        self._clear_guides()
        tolerance = 7 / self.transform().m11()
        pen = QPen(self.palette().color(QPalette.ColorRole.Highlight), 1, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        for axis, offsets in (("x", (0, 150, 300)), ("y", (0, 40, 80))):
            matches = []
            for other in self._link_nodes.values():
                if other is node:
                    continue
                for offset in offsets:
                    for other_offset in offsets:
                        target = getattr(other.pos(), axis)() + other_offset
                        delta = target - (getattr(position, axis)() + offset)
                        if abs(delta) <= tolerance:
                            matches.append((abs(delta), delta, target, other))
            if matches:
                _, delta, target, other = min(matches, key=lambda match: match[0])
                if axis == "x":
                    position.setX(position.x() + delta)
                    guide = self.scene().addLine(target, min(position.y(), other.y()) - 20, target, max(position.y(), other.y()) + 100, pen)
                else:
                    position.setY(position.y() + delta)
                    guide = self.scene().addLine(min(position.x(), other.x()) - 20, target, max(position.x(), other.x()) + 320, target, pen)
                guide.setZValue(-2)
                self._guides.append(guide)
        return position

    def _set_link_target(self, target):
        if target is self._link_target:
            return
        if self._link_target is not None:
            self._link_target.link_target = False
            self._link_target.update()
        self._link_target = target
        if target is not None:
            target.link_target = True
            target.update()

    def mouseMoveEvent(self, event):
        position = self.mapToScene(event.position().toPoint())
        if self._link_source is not None:
            source = self._node_at_index(self._link_source)
            start = source.anchor(self._link_port)
            cards = (source.rect().translated(source.pos()),)
            target = self.itemAt(event.position().toPoint())
            valid = isinstance(target, _FlowNode) and target is not source and target.data(0) >= 0
            if valid and self.connection_allowed is not None:
                valid = self.connection_allowed(self._link_source, target.data(0))
            self._set_link_target(target if valid else None)
            incoming = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}[self._link_port]
            if valid:
                local = target.mapFromScene(position)
                incoming = min(target.PORTS, key=lambda name: (local - target.PORTS[name]).manhattanLength())
                position = target.anchor(incoming)
                cards += (target.rect().translated(target.pos()),)
            pen = self._connection_pen(preview=True)
            if isinstance(target, _FlowNode) and not valid:
                pen.setColor(QColor("#dc2626"))
            self._link_preview.setPen(pen)
            self._link_preview.setPath(self._connection_path(start, position, self._link_port, incoming, cards))
            event.accept()
            return
        if self._editable and self._drag_index is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if (event.position().toPoint() - self._press_pos).manhattanLength() >= QApplication.startDragDistance():
                node = self._node_at_index(self._drag_index)
                destination = self._drag_origin + position - self.mapToScene(self._press_pos)
                node.setPos(self._snap_position(node, destination))
                self._draw_edges()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._selection_press and event.button() == Qt.MouseButton.LeftButton:
            # The view did not receive the press, so its hand-drag release
            # must not treat this as an empty-canvas click and clear selection.
            self._selection_press = False
            event.accept()
            return
        if self._add_arrow_press is not None and event.button() == Qt.MouseButton.LeftButton:
            index, direction = self._add_arrow_press
            self._add_arrow_press = None
            point = event.position().toPoint()
            item = self.itemAt(point)
            if self._editable and isinstance(item, _FlowNode) and item.data(0) == index:
                local = item.mapFromScene(self.mapToScene(point))
                if item.add_direction_at(local) == direction:
                    self._open_add_menu(event.globalPosition().toPoint(), index=index, direction=direction)
            event.accept()
            return
        source = self._link_source
        self._link_source = None
        if source is not None:
            self._set_link_target(None)
            self.scene().removeItem(self._link_preview)
            self._link_preview = None
            target = self.itemAt(event.position().toPoint())
            if isinstance(target, _FlowNode) and 0 <= target.data(0) != source:
                local = target.mapFromScene(self.mapToScene(event.position().toPoint()))
                incoming = min(target.PORTS, key=lambda name: (local - target.PORTS[name]).manhattanLength())
                self.connection_requested.emit(source, target.data(0), self._link_port, incoming)
            self._drag_index = None
            event.accept()
            return
        index = self._drag_index
        self._drag_index = None
        self._clear_guides()
        super().mouseReleaseEvent(event)
        if self._editable and index is not None:
            node = self._node_at_index(index)
            if node.pos() != self._drag_origin:
                self.position_changed.emit(index, [node.x(), node.y()])
                self._expand_canvas()

    def _open_add_menu(self, position, *, index=None, direction=None, endpoints=None):
        menu = QMenu(self)
        if endpoints is not None:
            title = "插入节点"
        else:
            node = self._node_at_index(index)
            has_outgoing = any(self._link_nodes[source] is node for source, *_ in self._links)
            title = ("新增并行分支" if self.parallel_enabled else "插入节点") if has_outgoing else "添加下一步"
        menu.addSection(str(tr(title)))
        for category, kinds in CATEGORIES.items():
            submenu = menu.addMenu(str(tr(category)))
            for kind in kinds:
                action = submenu.addAction(str(tr(STEP_LABELS[kind])))
                action.setData(kind)
        try:
            chosen = menu.exec(position)
            if chosen is not None and chosen.data() in STEP_LABELS:
                if endpoints is not None:
                    self.edge_insert_requested.emit(endpoints, chosen.data())
                else:
                    self.module_add_requested.emit(index, direction, chosen.data())
        finally:
            menu.deleteLater()

    def _accept_drag(self, event):
        mime = event.mimeData()
        return self._editable and isinstance(event.source(), ModuleLibrary) and mime.hasFormat("application/x-pipeterminal-module")

    def dragEnterEvent(self, event):
        if self._accept_drag(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if not self._accept_drag(event):
            event.ignore()
            return
        self.drop_position = self.mapToScene(event.position().toPoint())
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.drop_position = None
        self.viewport().update()
        event.accept()

    def dropEvent(self, event):
        if not self._accept_drag(event):
            event.ignore()
            return
        self.drop_position = self.mapToScene(event.position().toPoint())
        event.acceptProposedAction()
        module = bytes(event.mimeData().data("application/x-pipeterminal-module")).decode("utf-8")
        try:
            if module in STEP_LABELS:
                self.module_dropped.emit(module, len(self._nodes))
        finally:
            self.drop_position = None

    def selected_step_indexes(self):
        return tuple(sorted(item.data(0) for item in self.scene().selectedItems() if isinstance(item, _FlowNode)))

    def select_step(self, index, *, reveal=True):
        blocker = QSignalBlocker(self.scene())
        self.scene().clearSelection()
        if 0 <= index < len(self._nodes):
            self._nodes[index].setSelected(True)
            if reveal:
                self.ensureVisible(self._nodes[index])
        del blocker

    def _selected(self):
        indexes = self.selected_step_indexes()
        self.step_selected.emit(indexes[0] if indexes else -1)

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        while item is not None and not isinstance(item, QGraphicsRectItem):
            item = item.parentItem()
        if isinstance(item, _FlowNode) and item.data(0) >= 0:
            if event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.mousePressEvent(event)
                return
            self.step_selected.emit(item.data(0))
            self.step_activated.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class ModuleLibrary(QTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        QApplication.instance().installEventFilter(self)
        self.setHeaderHidden(True)
        self.setIndentation(12)
        self.setIconSize(QSize(20, 20))
        self.setStyleSheet("QTreeWidget { border: none; background: palette(base); } QTreeWidget::item { padding: 9px 6px; margin: 3px 0; border-radius: 6px; } QTreeWidget::item:hover { background: palette(alternate-base); } QTreeWidget::item:selected { background: palette(highlight); color: palette(highlighted-text); }")
        self.setDragEnabled(True)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setToolTip(tr("拖动模块到中间流程画布后编辑参数"))
        for group, kinds in CATEGORIES.items():
            category = QTreeWidgetItem(self, [tr(group)])
            category.setFlags(category.flags() & ~Qt.ItemFlag.ItemIsDragEnabled & ~Qt.ItemFlag.ItemIsEditable & ~Qt.ItemFlag.ItemIsSelectable)
            for kind in kinds:
                item = QTreeWidgetItem(category, [tr(STEP_LABELS[kind])])
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setData(0, Qt.ItemDataRole.UserRole, kind)
                icon = QStyle.StandardPixmap.SP_ComputerIcon if kind.startswith("LOCAL") or kind == "OPEN_SHELL" else QStyle.StandardPixmap.SP_DriveNetIcon if kind.startswith("REMOTE") else QStyle.StandardPixmap.SP_ArrowUp if kind in UPLOAD_LABELS else QStyle.StandardPixmap.SP_FileDialogDetailedView if kind == "MAVEN_BUILD" else QStyle.StandardPixmap.SP_MediaPause if kind == "WAIT" else QStyle.StandardPixmap.SP_DialogApplyButton if kind == "HEALTH_CHECK" else None
                item.setIcon(0, self.style().standardIcon(icon) if icon is not None else self._git_icon())
                item.setToolTip(0, str(tr(STEP_LABELS[kind])))
            font = category.font(0)
            font.setBold(True)
            category.setFont(0, font)
            category.setExpanded(True)

    @staticmethod
    def _git_icon():
        pixmap = QPixmap(48, 48)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        diamond = QPainterPath(QPointF(24, 2))
        for point in (QPointF(46, 24), QPointF(24, 46), QPointF(2, 24)):
            diamond.lineTo(point)
        diamond.closeSubpath()
        painter.fillPath(diamond, QColor("#f05032"))
        painter.setPen(QPen(Qt.GlobalColor.white, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(18, 14, 18, 33)
        painter.drawLine(18, 14, 32, 25)
        painter.setBrush(Qt.GlobalColor.white)
        for point in (QPointF(18, 14), QPointF(18, 33), QPointF(32, 25)):
            painter.drawEllipse(point, 3, 3)
        painter.end()
        return QIcon(pixmap)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonPress and isinstance(watched, QWidget):
            if watched is not self and not self.isAncestorOf(watched):
                self.clearSelection()
                self.setCurrentItem(None)
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item is None or not item.flags() & Qt.ItemFlag.ItemIsSelectable:
            self.clearSelection()
            self.setCurrentItem(None)
        super().mousePressEvent(event)

    def startDrag(self, supported_actions):
        item = self.currentItem()
        if item is None or not item.data(0, Qt.ItemDataRole.UserRole):
            return
        mime = QMimeData()
        mime.setData("application/x-pipeterminal-module", item.data(0, Qt.ItemDataRole.UserRole).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


def parameter_summary(steps, selected=None):
    labels = FIELD_LABELS
    indexes = [selected] if selected is not None and 0 <= selected < len(steps) else range(len(steps))
    lines = []
    for index in indexes:
        step = steps[index]
        label = STEP_LABELS.get(step["type"], step["type"])
        lines.append(str(tr("{0}. {1}", index + 1, tr(label))))
        properties = dict(step.get("properties", {}))
        if step["type"] in EXECUTION_LABELS:
            properties.pop("FAILURE_POLICY", None)
            properties.pop("CLEANUP", None)
            mode = properties.setdefault("EXECUTION_MODE", "script" if step["type"].endswith("SCRIPT") else "command")
            hidden = {"COMMAND"} if mode == "script" else {"SCRIPT_CONTENT", "SCRIPT_PATH", "SCRIPT_SOURCE", "ARGUMENTS"}
            hidden.update({"SCRIPT_PATH", "SCRIPT_SOURCE"})
            if not step["type"].startswith("REMOTE"):
                hidden.update({"SERVER", "SCRIPT_SOURCE"})
            properties = {key: value for key, value in properties.items() if key not in hidden}
        elif step["type"] in UPLOAD_LABELS and step["type"] != "UPLOAD_JAR":
            properties.pop("JAR_FILTER", None)
            properties.pop("ARTIFACT_NAME", None)
        elif step["type"] not in UPLOAD_LABELS and step["type"] not in {"MAVEN_BUILD", "WAIT", "HEALTH_CHECK", "OPEN_SHELL"}:
            properties.setdefault("CONFLICT_POLICY", "rollback")
        if step["type"] == "UPLOAD_JAR":
            properties.pop("UPLOAD_SOURCE", None)
        for key, value in properties.items():
            if key == "CONFLICT_POLICY":
                value = tr(POLICIES.get(value, "回退"))
            elif key == "UPLOAD_CREATE_DIRECTORY":
                value = tr("是" if value == "yes" else "否")
            elif key == "UPLOAD_CONFLICT":
                value = tr(UPLOAD_POLICIES.get(value, value))
            elif key in CHOICES:
                value = tr(CHOICES[key].get(value, value))
            caption = "项目目录" if step["type"] == "UPLOAD_JAR" and key == "UPLOAD_SOURCE" else labels.get(key, key)
            lines.append(f"{tr(caption)}: {value}")
        lines.append("")
    return "\n".join(lines).strip()
