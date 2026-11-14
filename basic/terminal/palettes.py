"""Shell color presets shared by the terminal and its settings preview."""

from dataclasses import dataclass


DARK_ANSI = (
    "#18181b", "#cd3131", "#0dbc79", "#e5e510", "#2472c8", "#bc3fbc", "#11a8cd", "#e5e5e5",
    "#666666", "#f14c4c", "#23d18b", "#f5f543", "#3b8eea", "#d670d6", "#29b8db", "#ffffff",
)
LIGHT_ANSI = (
    "#18181b", "#b91c1c", "#15803d", "#a16207", "#1d4ed8", "#a21caf", "#0e7490", "#4b5563",
    "#71717a", "#dc2626", "#16a34a", "#ca8a04", "#2563eb", "#c026d3", "#0891b2", "#27272a",
)


@dataclass(frozen=True)
class ShellPalette:
    name: str
    background: str
    foreground: str
    selection: str
    selection_text: str
    scroll_thumb: str
    ansi: tuple[str, ...]


DEFAULT_SHELL_THEME = "default"
SHELL_COLOR_FIELDS = (
    ("background", "窗口背景"), ("foreground", "正文颜色"),
    ("selection", "选中底色"), ("selection_text", "选中文字"),
    ("scroll_thumb", "滚动条滑块"),
)
SHELL_THEMES = {
    DEFAULT_SHELL_THEME: ShellPalette(
        "经典深色", "#111827", "#e5e7eb", "#374151", "#ffffff", "#475569", DARK_ANSI,
    ),
    "high-contrast": ShellPalette(
        "深色高对比", "#0b0d12", "#f8fafc", "#283d66", "#ffffff", "#71829b",
        (
            "#0b0d12", "#ff858d", "#80e6a6", "#ffe187", "#81b7ff", "#e5a4ff", "#78e4ed", "#e5e7eb",
            "#8a96aa", "#ffadb3", "#a6f4bf", "#ffedaa", "#abcfff", "#f1c4ff", "#a9f4fa", "#ffffff",
        ),
    ),
    "light": ShellPalette(
        "浅色", "#f8fafc", "#1e293b", "#dbeafe", "#172554", "#94a3b8", LIGHT_ANSI,
    ),
}
