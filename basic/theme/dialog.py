"""Compact theme selection with live preview and cancel restoration."""

from PySide6.QtCore import QEvent, QSignalBlocker
from PySide6.QtWidgets import QComboBox, QDialogButtonBox, QHBoxLayout, QMessageBox, QVBoxLayout, QWidget

from common.i18n import tr
from common.i18n.manager import get_manager as get_language_manager
from common.i18n.widgets import QDialog, QFormLayout, QLabel

from .manager import get_manager
from .palettes import THEMES

from common.i18n.errors import error_message


class ThemeDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._manager = get_manager()
        self._original_theme = self._manager.theme_id
        self.setWindowTitle(tr("主题"))
        self.resize(320, 180)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.choices = QComboBox()
        for theme in THEMES.values():
            self.choices.addItem(tr(theme.name), theme.id)
        form.addRow(tr("主题："), self.choices)
        layout.addLayout(form)
        preview = QHBoxLayout()
        self.swatches: list[QLabel] = []
        for _ in range(5):
            swatch = QLabel()
            swatch.setFixedSize(32, 20)
            self.swatches.append(swatch)
            preview.addWidget(swatch)
        preview.addStretch(1)
        self.kind_label = QLabel()
        preview.addWidget(self.kind_label)
        layout.addLayout(preview)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self._save_theme)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.choices.currentIndexChanged.connect(self._preview_theme)
        get_language_manager().language_changed.connect(self._refresh_theme_names)

    def showEvent(self, event: QEvent) -> None:
        self._original_theme = self._manager.theme_id
        blocker = QSignalBlocker(self.choices)
        self.choices.setCurrentIndex(self.choices.findData(self._original_theme))
        del blocker
        self._refresh_theme_names()
        self._preview_theme()
        super().showEvent(event)

    def _refresh_theme_names(self, _language: str = "") -> None:
        blocker = QSignalBlocker(self.choices)
        for index, theme in enumerate(THEMES.values()):
            self.choices.setItemText(index, tr(theme.name))
        del blocker

    def _preview_theme(self, _index: int = -1) -> None:
        theme = THEMES[self.choices.currentData()]
        for swatch, color in zip(
            self.swatches,
            (theme.background, theme.surface, theme.sidebar, theme.foreground, theme.accent),
        ):
            swatch.setStyleSheet(f"background:{color}; border:1px solid {theme.border}; border-radius:4px;")
            swatch.setToolTip(color)
        self.kind_label.setText(tr("深色") if theme.dark else tr("浅色"))
        self._manager.apply_theme(theme.id)

    def _save_theme(self) -> None:
        try:
            self._manager.set_theme(self.choices.currentData())
        except OSError as exc:
            QMessageBox.critical(self, tr("保存失败"), tr("无法保存主题设置") + f"\n{error_message(exc)}")
            return
        self._original_theme = self._manager.theme_id
        self.accept()

    def reject(self) -> None:
        self._manager.apply_theme(self._original_theme)
        super().reject()
