"""Compact theme selection with live preview and cancel restoration."""

from html import escape

from PySide6.QtCore import QEvent, QSignalBlocker, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QComboBox, QDialogButtonBox, QFrame, QHBoxLayout, QMessageBox, QVBoxLayout, QWidget

from basic.terminal.palettes import SHELL_THEMES, ShellPalette
from common.i18n import tr
from common.i18n.manager import get_manager as get_language_manager
from common.configuration.codec import ConfigurationEncryptionError
from common.i18n.widgets import QDialog, QFormLayout, QLabel, QPushButton

from .custom_dialog import CustomThemeDialog
from .manager import get_manager
from .palettes import THEMES

from common.i18n.errors import error_message


_CUSTOM_THEME_OPTION = "new-custom-theme"


class ThemeDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._manager = get_manager()
        self._original_theme = self._manager.theme_id
        self._original_shell_theme = self._manager.shell_theme_id
        self.setWindowTitle(tr("主题"))
        self.resize(520, 420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(10)
        layout.addWidget(self._section_title(tr("主界面主题")))
        form = QFormLayout()
        self.choices = QComboBox()
        form.addRow(tr("主题："), self.choices)
        layout.addLayout(form)
        custom_actions = QHBoxLayout()
        self._edit_button = QPushButton(tr("编辑自定义主题"))
        self._edit_button.setAutoDefault(False)
        self._edit_button.clicked.connect(lambda: self._open_custom_theme(editing=True))
        custom_actions.addWidget(self._edit_button)
        custom_actions.addStretch(1)
        layout.addLayout(custom_actions)
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
        layout.addSpacing(10)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFixedHeight(1)
        separator.setStyleSheet("background: palette(mid); border: none;")
        layout.addWidget(separator)
        layout.addSpacing(10)
        layout.addWidget(self._section_title(tr("Shell 主题")))
        shell_actions = QHBoxLayout()
        self.shell_choices = QComboBox()
        shell_actions.addWidget(self.shell_choices, 1)
        self._shell_edit_button = QPushButton(tr("编辑自定义主题"))
        self._shell_edit_button.setAutoDefault(False)
        self._shell_edit_button.clicked.connect(lambda: self._open_custom_shell_theme(editing=True))
        shell_actions.addWidget(self._shell_edit_button)
        layout.addLayout(shell_actions)
        self._shell_preview = QLabel()
        self._shell_preview.setTextFormat(Qt.TextFormat.RichText)
        font = QFont("Cascadia Mono", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._shell_preview.setFont(font)
        self._shell_preview.setMinimumHeight(82)
        layout.addWidget(self._shell_preview)
        layout.addStretch(1)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self._save_theme)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.choices.currentIndexChanged.connect(self._choose_theme)
        self.shell_choices.currentIndexChanged.connect(self._choose_shell_theme)
        self._manager.shell_theme_changed.connect(self._paint_shell_preview)
        get_language_manager().language_changed.connect(self._refresh_theme_names)

    @staticmethod
    def _section_title(text: str) -> QLabel:
        title = QLabel(text)
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        return title

    def showEvent(self, event: QEvent) -> None:
        self._original_theme = self._manager.theme_id
        self._original_shell_theme = self._manager.shell_theme_id
        self._populate_themes(self._original_theme)
        self._populate_shell_themes(self._original_shell_theme)
        self._preview_theme()
        super().showEvent(event)

    def _refresh_theme_names(self, _language: str = "") -> None:
        self._populate_themes(self.choices.currentData())
        self._populate_shell_themes(self._manager.shell_theme_id)

    def _populate_shell_themes(self, selected_id: str) -> None:
        with QSignalBlocker(self.shell_choices):
            self.shell_choices.clear()
            for theme_id, theme in self._manager.shell_themes.items():
                name = tr(theme.name) if theme_id in SHELL_THEMES else theme.name
                self.shell_choices.addItem(name, theme_id)
            self.shell_choices.addItem(tr("自定义主题…"), _CUSTOM_THEME_OPTION)
            self.shell_choices.setCurrentIndex(self.shell_choices.findData(selected_id))
        self._preview_shell_theme()

    def _choose_shell_theme(self, _index: int) -> None:
        if self.shell_choices.currentData() == _CUSTOM_THEME_OPTION:
            with QSignalBlocker(self.shell_choices):
                self.shell_choices.setCurrentIndex(self.shell_choices.findData(self._manager.shell_theme_id))
            self._open_custom_shell_theme(editing=False)
        else:
            self._preview_shell_theme()

    def _open_custom_shell_theme(self, *, editing: bool) -> None:
        theme_id = self.shell_choices.currentData()
        editor = CustomThemeDialog(
            self._manager, self._manager.shell_themes[theme_id],
            editing=editing, parent=self, shell_id=theme_id,
        )
        if editor.exec() == QDialog.DialogCode.Accepted:
            self._original_shell_theme = editor.theme_id
            self._populate_shell_themes(editor.theme_id)
        else:
            self._preview_shell_theme()
        editor.deleteLater()

    def _preview_shell_theme(self) -> None:
        theme_id = self.shell_choices.currentData()
        self._shell_edit_button.setEnabled(theme_id not in SHELL_THEMES)
        self._manager.apply_shell_theme(theme_id)
        self._paint_shell_preview(self._manager.shell_palette)

    def _paint_shell_preview(self, theme: ShellPalette) -> None:
        self._shell_preview.setStyleSheet(
            f"background: {theme.background}; color: {theme.foreground};"
            "border-radius: 5px; padding: 8px;"
        )
        error = escape(tr("无法读取文件"))
        self._shell_preview.setText(
            f'<span style="color:{theme.foreground}">'
            f'<span style="color:{theme.ansi[2]}">user@server:~$</span> ls<br>'
            f'<span style="color:{theme.ansi[12]}">logs/</span>&nbsp;&nbsp;README.md<br>'
            f'<span style="color:{theme.ansi[1]}">cat: {error}</span></span>'
        )

    def _populate_themes(self, selected_id: str | None) -> None:
        with QSignalBlocker(self.choices):
            self.choices.clear()
            for theme in self._manager.themes.values():
                name = tr(theme.name) if theme.id in THEMES else theme.name
                self.choices.addItem(name, theme.id)
            self.choices.addItem(tr("自定义主题…"), _CUSTOM_THEME_OPTION)
            index = self.choices.findData(selected_id)
            self.choices.setCurrentIndex(max(0, index))

    def _choose_theme(self, _index: int) -> None:
        if self.choices.currentData() == _CUSTOM_THEME_OPTION:
            with QSignalBlocker(self.choices):
                self.choices.setCurrentIndex(self.choices.findData(self._manager.theme_id))
            self._open_custom_theme(editing=False)
        else:
            self._preview_theme()

    def _open_custom_theme(self, *, editing: bool) -> None:
        theme = self._manager.themes[self.choices.currentData()]
        editor = CustomThemeDialog(self._manager, theme, editing=editing, parent=self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            self._original_theme = editor.theme_id
            self._populate_themes(editor.theme_id)
        self._preview_theme()
        editor.deleteLater()

    def _preview_theme(self) -> None:
        theme = self._manager.themes[self.choices.currentData()]
        self._edit_button.setEnabled(theme.id not in THEMES)
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
            self._manager.set_theme(
                self.choices.currentData(), shell_theme_id=self.shell_choices.currentData()
            )
        except (OSError, ConfigurationEncryptionError) as exc:
            QMessageBox.critical(self, tr("保存失败"), tr("无法保存主题设置") + f"\n{error_message(exc)}")
            return
        self._original_theme = self._manager.theme_id
        self._original_shell_theme = self._manager.shell_theme_id
        self.accept()

    def reject(self) -> None:
        self._manager.apply_shell_theme(self._original_shell_theme)
        self._manager.apply_theme(self._original_theme)
        super().reject()
