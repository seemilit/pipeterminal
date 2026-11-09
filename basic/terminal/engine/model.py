"""Portable cell data shared by Python and future native engine adapters."""

from dataclasses import dataclass, field


Color = int | tuple[int, int, int] | None


@dataclass(frozen=True, slots=True)
class Cell:
    text: str = " "
    foreground: Color = None
    background: Color = None
    bold: bool = False
    underline: bool = False
    italic: bool = False
    inverse: bool = False
    width: int = 1
    input: bool = False
    context_id: int | None = None

    @property
    def continuation(self) -> bool:
        return self.width == 0


@dataclass(slots=True)
class Line:
    id: int
    cells: list[Cell] = field(default_factory=list)
    wrapped: bool = False
    prompt_path: tuple[int, int] | None = None
    prompt_directory: str = ""
    prompt_context: int | None = None
    input_start: int | None = None
    path_enabled: bool = True


@dataclass(slots=True)
class Cursor:
    row: int = 0
    col: int = 0
    visible: bool = True
    style: str = "block"


@dataclass(frozen=True, slots=True)
class Damage:
    line_ids: frozenset[int]
    full: bool
    history_changed: bool
