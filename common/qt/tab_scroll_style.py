"""Place overflowing panel-tab controls at opposite ends of the bar."""

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QProxyStyle, QStyle


class PanelTabScrollStyle(QProxyStyle):
    def __init__(self, parent=None) -> None:
        super().__init__("Fusion")
        self.setParent(parent)

    def pixelMetric(self, metric, option=None, widget=None):
        if metric == QStyle.PixelMetric.PM_TabBarScrollButtonWidth:
            return 36
        return super().pixelMetric(metric, option, widget)

    def subElementRect(self, element, option, widget=None):
        if element in {
            QStyle.SubElement.SE_TabBarScrollLeftButton,
            QStyle.SubElement.SE_TabBarScrollRightButton,
        }:
            width = self.pixelMetric(QStyle.PixelMetric.PM_TabBarScrollButtonWidth, option, widget)
            rect = option.rect
            left = rect.left() if element == QStyle.SubElement.SE_TabBarScrollLeftButton else rect.right() - width + 1
            button_rect = QRect(left, rect.top(), width, rect.height())
            return QStyle.visualRect(option.direction, rect, button_rect)
        if element in {
            QStyle.SubElement.SE_TabBarTearIndicatorLeft,
            QStyle.SubElement.SE_TabBarTearIndicatorRight,
        }:
            return QRect()
        return super().subElementRect(element, option, widget)
