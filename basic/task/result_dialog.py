"""Compact, per-step summary for interrupted workflow runs."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from common.i18n import tr
from common.i18n.widgets import QDialog, QLabel, QPushButton


class RunResultDialog(QDialog):
    def __init__(self, record, indexes, labels, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("执行结果"))
        self.setMinimumWidth(540)
        self.resize(600, 480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)
        stopped = record["state"] == "stopped"
        heading = QLabel(tr("任务已停止") if stopped else tr("执行失败"))
        font = heading.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)
        subtitle = QLabel(title)
        subtitle.setTextFormat(Qt.TextFormat.PlainText)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        groups = {"success": [], "interrupted": [], "pending": []}
        for index in sorted(indexes):
            step = record["steps"][index]
            group = ("success" if step["state"] == "success" else
                     "interrupted" if step["started"] is not None else "pending")
            groups[group].append((index, step))
        names = {"success": tr("已完成"), "interrupted": tr("已中断"), "pending": tr("未执行")}
        summary = QHBoxLayout()
        for key, steps in groups.items():
            card = QFrame()
            card.setObjectName("settingsCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            count = QLabel(str(len(steps)))
            count.setFont(font)
            card_layout.addWidget(count)
            card_layout.addWidget(QLabel(names[key]))
            summary.addWidget(card, 1)
        layout.addLayout(summary)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        details = QVBoxLayout(content)
        details.setContentsMargins(0, 0, 8, 0)
        details.setSpacing(10)
        for key, steps in groups.items():
            if not steps:
                continue
            section = QLabel(names[key])
            section_font = section.font()
            section_font.setBold(True)
            section.setFont(section_font)
            details.addWidget(section)
            for index, step in steps:
                row = QLabel(tr("第 {0} 步：{1}", index + 1, tr(labels.get(step["type"], step["type"]))))
                row.setTextFormat(Qt.TextFormat.PlainText)
                row.setWordWrap(True)
                row.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                details.addWidget(row)
        details.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        note = QLabel(tr("已完成的操作不会撤销；中断步骤可能已产生部分结果。") if stopped else record["message"])
        note.setTextFormat(Qt.TextFormat.PlainText)
        note.setWordWrap(True)
        note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(note)
        buttons = QHBoxLayout()
        buttons.addStretch()
        close = QPushButton(tr("关闭"))
        close.setMinimumWidth(88)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)
