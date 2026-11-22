"""Public shell integration contract for feature-owned editor pages."""

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget


class ModulePage(QWidget):
    uses_panel_workspace = False
    fills_panel_workspace = False
    provides_focus_status = False
    workspace_item_id: str | None = None
    workspace_module_id: str | None = None
    workspace_icon: str | None = None
    workspace_numbered = False

    directory_changed = Signal()
    workspace_directory_changed = Signal()
    directory_item_renamed = Signal(str, str)
    actions_changed = Signal()
    status_changed = Signal(object)
    bottom_panel_requested = Signal(str, object, object)
    bottom_panel_removed = Signal(str)
    close_requested = Signal()
    new_panel_requested = Signal()
    duplicate_panel_requested = Signal()
    panel_focus_requested = Signal(object, bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.file_actions: dict[str, Callable[[], object]] = {}

    def bind_registry(self, registry) -> None:
        self.registry = registry

    def activate(self) -> None:
        pass

    def activate_with_selection(self, item_id: str | None) -> None:
        self.activate()
        if item_id is not None and any(key == item_id for key, _ in self.directory_items()):
            self.select_item(item_id)

    def directory_items(self) -> list[tuple[str, str]]:
        return []

    def current_item_id(self) -> str | None:
        return None

    def select_item(self, item_id: str) -> bool:
        return True

    def activate_item(self, item_id: str) -> None:
        pass

    def workspace_item_actions(self, item_id: str):
        return ()

    def workspace_background_active(self) -> bool:
        return False

    def is_action_enabled(self, action_id: str) -> bool:
        return action_id in self.file_actions

    def action_label(self, action_id: str) -> str | None:
        return None

    def action_tooltip(self, action_id: str) -> str | None:
        return None

    def set_panel_focus(self, focused: bool) -> None:
        """Optionally adjust the panel's contents in workspace focus mode."""

    def can_duplicate_panel(self) -> bool:
        return False

    def can_disconnect_panel(self) -> bool:
        return False

    def disconnect_panel(self) -> None:
        pass

    def can_leave(self) -> bool:
        return True
