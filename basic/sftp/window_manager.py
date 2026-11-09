"""Application-wide SFTP view limit with an optional registry policy."""


class TransferWindowManager:
    def __init__(self):
        self._windows = {}
        self._opening = False

    @property
    def has_windows(self) -> bool:
        return bool(self._windows)

    def admit(self, dialog, close, policy=None):
        if self._opening:
            return False
        self._opening = True
        try:
            limit = policy.max_windows if policy is not None else 1
            existing = tuple(self._windows.items())
            replacing = existing if limit == 1 else ()
            if any(not old.can_close() for old, _close in replacing if old in self._windows):
                return False
            # Register the replacement first so its Shell keeps the shared session alive.
            self._windows[dialog] = close
            for old, close_old in replacing:
                if old in self._windows:
                    close_old()
            return True
        finally:
            self._opening = False

    def remove(self, dialog):
        self._windows.pop(dialog, None)
