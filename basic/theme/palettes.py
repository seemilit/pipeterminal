"""Theme tokens adapted from official Nord, Catppuccin and Dracula palettes.

https://www.nordtheme.com/docs/colors-and-palettes/
https://catppuccin.com/palette/
https://draculatheme.com/spec
"""

import re
from dataclasses import dataclass

from common.i18n import tr


COLOR_FIELDS = (
    ("background", "窗口背景"), ("surface", "面板底色"), ("sidebar", "侧栏底色"),
    ("foreground", "正文颜色"), ("muted", "次要文字"), ("border", "边框颜色"),
    ("hover", "悬浮底色"), ("accent", "强调色"), ("selection", "选中底色"),
    ("selection_text", "选中文字"),
)


def normalize_color(value: object) -> str:
    value = value.strip() if isinstance(value, str) else ""
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
        return value.lower()
    match = re.fullmatch(
        r"rgb\(\s*([0-9]{1,3})\s*,\s*([0-9]{1,3})\s*,\s*([0-9]{1,3})\s*\)", value, re.IGNORECASE
    )
    if match:
        rgb = tuple(map(int, match.groups()))
        if max(rgb) <= 255:
            return "#" + "".join(f"{component:02x}" for component in rgb)
    raise ValueError(tr("请输入 #RRGGBB 或 rgb(r, g, b)，RGB 分量必须在 0 到 255 之间。"))


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
