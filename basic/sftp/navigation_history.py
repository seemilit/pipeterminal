"""Confirmed directory visits, separate from the recent-path dropdown."""


class DirectoryNavigationHistory:
    def __init__(self) -> None:
        self._paths: list[str] = []
        self._index = -1
        self._pending_index: int | None = None

    @property
    def pending_directory(self) -> str | None:
        return self._paths[self._pending_index] if self._pending_index is not None else None

    @property
    def can_go_back(self) -> bool:
        position = self._pending_index if self._pending_index is not None else self._index
        return position > 0

    @property
    def can_go_forward(self) -> bool:
        position = self._pending_index if self._pending_index is not None else self._index
        return 0 <= position < len(self._paths) - 1

    def move(self, step: int) -> str | None:
        position = self._pending_index if self._pending_index is not None else self._index
        target = position + step
        if not 0 <= target < len(self._paths):
            return None
        self._pending_index = target
        return self._paths[target]

    def commit(self, directory: str, *, from_history: bool = False) -> None:
        target, self._pending_index = self._pending_index, None
        if from_history and target is not None:
            self._paths[target] = directory
            self._index = target
            return
        if self._index >= 0 and self._paths[self._index] == directory:
            return
        del self._paths[self._index + 1:]
        self._paths.append(directory)
        if len(self._paths) > 200:
            del self._paths[:-200]
        self._index = len(self._paths) - 1

    def cancel_pending(self) -> None:
        self._pending_index = None

    def reset(self) -> None:
        self._paths.clear()
        self._index = -1
        self._pending_index = None
