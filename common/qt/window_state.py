"""Window persistence using only the shared shell and ModulePage contract."""

from pathlib import Path

from PySide6.QtCore import QByteArray, QObject, QTimer, Qt

from common.settings.store import SettingsStore

from .module_page import ModulePage


class WindowStateController(QObject):
    def __init__(self, window, settings_path: Path) -> None:
        super().__init__(window)
        self.window = window
        self.store = SettingsStore(settings_path)
        try:
            self._state = self.store.read_section("window")
        except (OSError, ValueError):
            self._state = {}
        self._main_sizes = self._read_sizes("main_splitter_sizes", [280, 820])
        selected = self._state.get("selected_items")
        self._selected_items = {
            key: value for key, value in selected.items()
            if isinstance(key, str) and isinstance(value, str)
        } if isinstance(selected, dict) else {}
        self._restored_pages: set[str] = set()
        window.shell.main_splitter.splitterMoved.connect(self.remember_layout)

    def _read_sizes(self, key: str, default: list[int]) -> list[int]:
        value = self._state.get(key)
        if (
            isinstance(value, list) and len(value) == 2
            and all(type(size) is int and 0 < size <= 100000 for size in value)
        ):
            return list(value)
        return list(default)

    def restore_geometry(self) -> None:
        geometry = self._state.get("geometry")
        if isinstance(geometry, str) and len(geometry) <= 8192:
            try:
                self.window.restoreGeometry(QByteArray(bytes.fromhex(geometry)))
            except ValueError:
                pass
        if self._state.get("maximized") is True:
            self.window.setWindowState(self.window.windowState() | Qt.WindowState.WindowMaximized)

    def initial_module_id(self, available: list[str]) -> str | None:
        module_id = self._state.get("module_id")
        if not isinstance(module_id, str):
            return None
        return module_id if module_id in available else next(iter(available), None)

    def restore_page(self, module_id: str, page: ModulePage) -> None:
        if module_id in self._restored_pages:
            return
        self._restored_pages.add(module_id)
        item_id = self._selected_items.get(module_id)
        if item_id in {identifier for identifier, _name in page.directory_items()}:
            # Selection loads the editor only; activate_item could start SSH.
            page.select_item(item_id)

    def restore_layout(self) -> None:
        self._apply_layout()
        QTimer.singleShot(0, self._apply_layout)

    def _apply_layout(self) -> None:
        shell = self.window.shell
        shell.sidebar.show()
        shell.main_splitter.setSizes(self._main_sizes)
        visible = self._state.get("sidebar_visible") is not False
        self.window.sidebar_action.setChecked(visible)
        shell.sidebar.setVisible(visible)

    def remember_layout(self, *_args) -> None:
        main_sizes, _visible = self.window.shell.normal_layout()
        if all(size > 0 for size in main_sizes):
            self._main_sizes = list(main_sizes)

    def reset_layout(self) -> None:
        self._main_sizes = [250, 850]

    def save(self, module_id: str | None, pages: dict[str, object]) -> None:
        self.remember_layout()
        for identifier, page in pages.items():
            if isinstance(page, ModulePage):
                item_id = page.current_item_id()
                if isinstance(item_id, str):
                    self._selected_items[identifier] = item_id
                else:
                    self._selected_items.pop(identifier, None)
        _main_sizes, visible = self.window.shell.normal_layout()
        self.store.update_section("window", {
            "geometry": bytes(self.window.saveGeometry()).hex(),
            "maximized": self.window.isMaximized(),
            "main_splitter_sizes": self._main_sizes,
            "sidebar_visible": visible[1],
            "module_id": module_id,
            "selected_items": self._selected_items,
        })
