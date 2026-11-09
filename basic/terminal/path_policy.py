"""Optional registry extension; the public default never prefetches folders."""

from typing import Protocol


class PathPolicy(Protocol):
    prefetch: bool

    def get(self, key): ...
    def put(self, key, snapshot) -> None: ...
    def clear(self) -> None: ...


class ClickPathPolicy:
    prefetch = False

    def get(self, key):
        return None

    def put(self, key, snapshot) -> None:
        pass

    def clear(self) -> None:
        pass
