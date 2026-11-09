"""Small shared icons for navigation and toolbar actions."""

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QApplication


def create_icon(name: str, color: str | None = None) -> QIcon:
    if color is None:
        color = QApplication.palette().color(QPalette.ColorRole.WindowText).name()
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(16 / 24, 16 / 24)
    painter.setPen(QPen(
        QColor(color), 1.8, Qt.PenStyle.SolidLine,
        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin,
    ))
    painter.setBrush(Qt.BrushStyle.NoBrush)

    if name == "settings":
        points = []
        for index in range(32):
            angle = index * math.pi / 16
            radius = 9 if index % 4 in {0, 1} else 7
            points.append(QPointF(
                12 + math.cos(angle) * radius,
                12 + math.sin(angle) * radius,
            ))
        painter.drawPolygon(QPolygonF(points))
        painter.drawEllipse(QPointF(12, 12), 3, 3)
    elif name == "log":
        painter.drawRect(5, 3, 14, 18)
        for row in (8, 12, 16):
            painter.drawLine(8, row, 16, row)
    elif name == "terminal":
        painter.drawRect(3, 4, 18, 16)
        painter.drawPolyline(QPolygonF([QPointF(7, 9), QPointF(10, 12), QPointF(7, 15)]))
        painter.drawLine(13, 15, 17, 15)
    elif name == "connection":
        painter.drawRect(4, 3, 16, 7)
        painter.drawRect(4, 14, 16, 7)
        painter.drawLine(8, 6, 8, 7)
        painter.drawLine(8, 17, 8, 18)
        painter.drawLine(13, 6, 17, 6)
        painter.drawLine(13, 17, 17, 17)
    elif name == "theme":
        painter.drawEllipse(QPointF(12, 12), 4, 4)
        for index in range(8):
            angle = index * math.pi / 4
            painter.drawLine(
                QPointF(12 + math.cos(angle) * 7, 12 + math.sin(angle) * 7),
                QPointF(12 + math.cos(angle) * 10, 12 + math.sin(angle) * 10),
            )
    elif name == "language":
        painter.drawEllipse(QPointF(12, 12), 9, 9)
        painter.drawEllipse(8, 3, 8, 18)
        painter.drawLine(3, 12, 21, 12)
    elif name == "new":
        outline = QPainterPath(QPointF(5, 3))
        for x, y in ((14, 3), (19, 8), (19, 21), (5, 21)):
            outline.lineTo(x, y)
        outline.closeSubpath()
        painter.drawPath(outline)
        painter.drawPolyline(QPolygonF([
            QPointF(14, 3), QPointF(14, 8), QPointF(19, 8),
        ]))
        painter.drawLine(8, 14, 16, 14)
        painter.drawLine(12, 10, 12, 18)
    elif name == "rename":
        painter.drawPolygon(QPolygonF([
            QPointF(4, 16), QPointF(16, 4), QPointF(20, 8),
            QPointF(8, 20), QPointF(4, 20),
        ]))
        painter.drawLine(14, 6, 18, 10)
        painter.drawLine(4, 16, 8, 20)
    elif name == "copy":
        painter.drawRect(8, 8, 12, 13)
        painter.drawPolyline(QPolygonF([
            QPointF(5, 16), QPointF(3, 16), QPointF(3, 3),
            QPointF(15, 3), QPointF(15, 5),
        ]))
    elif name == "delete":
        painter.drawLine(4, 7, 20, 7)
        painter.drawRect(9, 3, 6, 4)
        painter.drawPolyline(QPolygonF([
            QPointF(6, 7), QPointF(7, 21), QPointF(17, 21), QPointF(18, 7),
        ]))
        painter.drawLine(10, 10, 10, 18)
        painter.drawLine(14, 10, 14, 18)
    elif name == "save":
        painter.drawRect(4, 3, 16, 18)
        painter.drawRect(8, 3, 8, 7)
        painter.drawRect(7, 14, 10, 7)
    elif name in {"eye", "eye_off"}:
        outline = QPainterPath(QPointF(2, 12))
        outline.cubicTo(7, 4, 17, 4, 22, 12)
        outline.cubicTo(17, 20, 7, 20, 2, 12)
        painter.drawPath(outline)
        painter.drawEllipse(QPointF(12, 12), 2.6, 2.6)
        if name == "eye_off":
            painter.drawLine(4, 4, 20, 20)
    elif name in {"sidebar", "bottom_panel"}:
        painter.drawRect(3, 4, 18, 16)
        if name == "sidebar":
            painter.drawLine(9, 4, 9, 20)
        else:
            painter.drawLine(3, 14, 21, 14)
    elif name == "reset_layout":
        outline = QPainterPath(QPointF(20, 8))
        outline.cubicTo(17, 2, 7, 2, 4, 8)
        outline.cubicTo(2, 14, 6, 20, 12, 20)
        outline.cubicTo(16, 20, 20, 16, 20, 12)
        painter.drawPath(outline)
        painter.drawPolyline(QPolygonF([
            QPointF(20, 3), QPointF(20, 8), QPointF(15, 8),
        ]))
    else:
        themed_icon = QIcon.fromTheme(name)
        if not themed_icon.isNull():
            painter.end()
            return themed_icon
        for x, y in ((4, 4), (14, 4), (4, 14), (14, 14)):
            painter.drawRect(x, y, 6, 6)

    painter.end()
    return QIcon(pixmap)
