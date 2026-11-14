"""Edit a named theme using RGB color codes."""

from uuid import uuid4

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QDialogButtonBox, QHBoxLayout, QMessageBox, QVBoxLayout, QWidget

from basic.terminal.palettes import SHELL_COLOR_FIELDS, ShellPalette
from common.configuration.codec import ConfigurationEncryptionError
from common.i18n import tr
from common.i18n.errors import error_message
from common.i18n.widgets import QCheckBox, QDialog, QFormLayout, QLabel, QLineEdit, QPushButton, QTabWidget

from .manager import ThemeManager
from .palettes import COLOR_FIELDS, ThemePalette, normalize_color


class CustomThemeDialog(QDialog):
    def __init__(
        self, manager: ThemeManager, base: ThemePalette | ShellPalette, *,
        editing: bool, parent: QWidget, shell_id: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._manager = manager
        self._base = base
        original_id = base.id if isinstance(base, ThemePalette) else shell_id
        self.theme_id = original_id if editing else f"custom-{uuid4().hex}"
        self.setWindowTitle(tr("编辑自定义主题") if editing else tr("新建自定义主题"))
        layout = QVBoxLayout(self)
        hint = QLabel(tr("颜色支持 #RRGGBB 或 rgb(r, g, b)。"))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QFormLayout()
        self._name = QLineEdit(base.name if editing else "")
        self._dark = None
        self._colors: dict[str, tuple[QLineEdit, str, str]] = {}
        self._tabs = None
        form.addRow(tr("主题名称"), self._name)
        layout.addLayout(form)
        if isinstance(base, ThemePalette):
            self._dark = QCheckBox(tr("深色"))
            self._dark.setChecked(base.dark)
            form.addRow(tr("主题类型"), self._dark)
            for field, label in COLOR_FIELDS:
                self._add_color_row(form, field, label, getattr(base, field))
        else:
            self._tabs = QTabWidget()
            general = QWidget()
            general_form = QFormLayout(general)
            for field, label in SHELL_COLOR_FIELDS:
                self._add_color_row(general_form, field, label, getattr(base, field))
            ansi_page = QWidget()
            ansi_layout = QHBoxLayout(ansi_page)
            for start, title in ((0, "标准色"), (8, "亮色")):
                column = QVBoxLayout()
                column.addWidget(QLabel(tr(title)))
                ansi_form = QFormLayout()
                for index in range(start, start + 8):
                    self._add_color_row(ansi_form, f"ansi{index}", f"ANSI {index}", base.ansi[index])
                column.addLayout(ansi_form)
                ansi_layout.addLayout(column, 1)
            self._tabs.addTab(general, tr("基础配色"))
            self._tabs.addTab(ansi_page, tr("ANSI 配色"))
            layout.addWidget(self._tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        preview = QPushButton(tr("预览"))
        preview.clicked.connect(self._preview)
        buttons.addButton(preview, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(600 if self._tabs else 430, self.sizeHint().height())
        self._name.setFocus()

    def _add_color_row(self, form: QFormLayout, field: str, label: str, initial: str) -> None:
        editor = QLineEdit(initial)
        editor.setPlaceholderText("#RRGGBB / rgb(0, 0, 0)")
        self._colors[field] = (editor, label, initial)
        swatch = QLabel()
        swatch.setFixedSize(28, 22)
        self._update_swatch(swatch, initial)
        editor.textChanged.connect(lambda text: self._update_swatch(swatch, text))
        picker = QPushButton(tr("取色…"))
        picker.setAutoDefault(False)
        picker.clicked.connect(lambda: self._pick_color(field))
        row = QHBoxLayout()
        row.addWidget(editor, 1)
        row.addWidget(swatch)
        row.addWidget(picker)
        form.addRow(tr(label), row)

    @staticmethod
    def _update_swatch(swatch: QLabel, text: str) -> None:
        try:
            color = normalize_color(text)
        except ValueError:
            swatch.setStyleSheet("background: transparent; border: 1px dashed palette(mid); border-radius: 4px;")
            swatch.setToolTip("")
            return
        swatch.setStyleSheet(f"background: {color}; border: 1px solid palette(mid); border-radius: 4px;")
        swatch.setToolTip(color)

    def _pick_color(self, field: str) -> None:
        editor, _label, initial = self._colors[field]
        try:
            initial = normalize_color(editor.text())
        except ValueError:
            pass
        color = QColorDialog.getColor(
            QColor(initial), self, tr("选择颜色"), QColorDialog.ColorDialogOption.DontUseNativeDialog
        )
        if color.isValid():
            editor.setText(color.name())

    def _read_theme(self, name: str) -> ThemePalette | ShellPalette | None:
        colors = {}
        for field, (editor, label, _initial) in self._colors.items():
            try:
                colors[field] = normalize_color(editor.text())
            except ValueError as exc:
                if self._tabs is not None:
                    self._tabs.setCurrentIndex(1 if field.startswith("ansi") else 0)
                QMessageBox.warning(self, tr(label), str(exc))
                editor.setFocus()
                editor.selectAll()
                return None
        if self._dark is None:
            ansi = tuple(colors.pop(f"ansi{index}") for index in range(16))
            return ShellPalette(name=name, ansi=ansi, **colors)
        return ThemePalette(self.theme_id, name, self._dark.isChecked(), **colors)

    def _preview(self) -> None:
        theme = self._read_theme(self._name.text().strip() or self._base.name)
        if isinstance(theme, ShellPalette):
            self._manager.preview_shell_theme(theme)
        elif theme is not None:
            self._manager.preview_theme(theme)

    def _save(self) -> None:
        name = self._name.text().strip()
        if not name:
            QMessageBox.warning(self, tr("主题名称"), tr("请输入主题名称"))
            self._name.setFocus()
            return
        theme = self._read_theme(name)
        if theme is None:
            return
        try:
            if isinstance(theme, ShellPalette):
                self._manager.save_custom_shell_theme(self.theme_id, theme)
            else:
                self._manager.save_custom_theme(theme)
        except (OSError, ConfigurationEncryptionError) as exc:
            QMessageBox.critical(self, tr("保存失败"), tr("无法保存主题设置") + f"\n{error_message(exc)}")
            return
        self.accept()
