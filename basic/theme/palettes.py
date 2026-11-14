"""Theme tokens adapted from official Nord, Catppuccin and Dracula palettes.

https://www.nordtheme.com/docs/colors-and-palettes/
https://catppuccin.com/palette/
https://draculatheme.com/spec
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemePalette:
    id: str
    name: str
    dark: bool
    background: str
    surface: str
    sidebar: str
    foreground: str
    muted: str
    border: str
    hover: str
    accent: str
    selection: str
    selection_text: str

    @property
    def accent_text(self) -> str:
        return self.background if self.dark else "#ffffff"


THEMES = {
    "white": ThemePalette(
        "white", "晨雾", False,
        "#f3f5f9", "#ffffff", "#edf0f5", "#202938", "#66758a",
        "#dfe4ed", "#f1f4f9", "#356ae6", "#e8efff", "#244fa8",
    ),
    "nord": ThemePalette(
        "nord", "北境", True,
        "#2e3440", "#3b4252", "#2e3440", "#eceff4", "#d8dee9",
        "#4c566a", "#434c5e", "#88c0d0", "#434c5e", "#eceff4",
    ),
    "catppuccin_latte": ThemePalette(
        "catppuccin_latte", "猫布奇诺·拿铁", False,
        "#e6e9ef", "#eff1f5", "#dce0e8", "#4c4f69", "#6c6f85",
        "#bcc0cc", "#ccd0da", "#8839ef", "#ccd0da", "#4c4f69",
    ),
    "catppuccin_mocha": ThemePalette(
        "catppuccin_mocha", "猫布奇诺·摩卡", True,
        "#181825", "#1e1e2e", "#11111b", "#cdd6f4", "#bac2de",
        "#313244", "#313244", "#cba6f7", "#45475a", "#cdd6f4",
    ),
    "dracula": ThemePalette(
        "dracula", "德古拉", True,
        "#21222c", "#282a36", "#21222c", "#f8f8f2", "#6272a4",
        "#44475a", "#44475a", "#bd93f9", "#44475a", "#f8f8f2",
    ),
}
