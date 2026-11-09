"""Visible square indicators independent of the active checkbox stylesheet."""

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QPainter, QPalette, QPen

from common.i18n.widgets import QCheckBox


class SquareCheckBox(QCheckBox):
    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        return QSize(30 + metrics.horizontalAdvance(self.text()), max(22, metrics.height() + 4))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, position) -> bool:
        return self.rect().contains(position)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        color = palette.color(
            QPalette.ColorRole.Text if self.isEnabled() else QPalette.ColorRole.PlaceholderText
        )
        top = max(0, (self.height() - 15) // 2)
        painter.setPen(QPen(color, 1))
        painter.setBrush(palette.color(QPalette.ColorRole.Base))
        painter.drawRect(QRect(1, top, 14, 14))
        if self.isChecked():
            painter.setPen(QPen(color, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(4, top + 7, 7, top + 10)
            painter.drawLine(7, top + 10, 13, top + 4)
        painter.setPen(color)
        painter.drawText(
            QRect(22, 0, max(0, self.width() - 22), self.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.text(),
        )
        painter.end()
