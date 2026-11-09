"""Translate Qt keyboard events to terminal bytes, never raw Qt key values."""

from PySide6.QtCore import Qt


_SPECIAL = {
    Qt.Key.Key_Return: b"\r", Qt.Key.Key_Enter: b"\r",
    Qt.Key.Key_Backspace: b"\x7f", Qt.Key.Key_Tab: b"\t",
    Qt.Key.Key_Backtab: b"\x1b[Z", Qt.Key.Key_Escape: b"\x1b",
    Qt.Key.Key_Insert: b"\x1b[2~", Qt.Key.Key_Delete: b"\x1b[3~",
    Qt.Key.Key_PageUp: b"\x1b[5~", Qt.Key.Key_PageDown: b"\x1b[6~",
}
_CURSOR = {
    Qt.Key.Key_Up: "A", Qt.Key.Key_Down: "B", Qt.Key.Key_Right: "C",
    Qt.Key.Key_Left: "D", Qt.Key.Key_Home: "H", Qt.Key.Key_End: "F",
}
_FUNCTIONS = [b"\x1bOP", b"\x1bOQ", b"\x1bOR", b"\x1bOS"] + [
    f"\x1b[{number}~".encode("ascii") for number in (15, 17, 18, 19, 20, 21, 23, 24)
]


def encode_key(key: int, text: str, modifiers, application_cursor: bool = False) -> bytes:
    control = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
    alt = bool(modifiers & Qt.KeyboardModifier.AltModifier)
    shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
    if key in _CURSOR:
        modifier = 1 + int(shift) + 2 * int(alt) + 4 * int(control)
        final = _CURSOR[key]
        return (f"\x1b[1;{modifier}{final}" if modifier > 1 else f"\x1b{'O' if application_cursor else '['}{final}").encode("ascii")
    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F12:
        data = _FUNCTIONS[key - Qt.Key.Key_F1]
    elif key in _SPECIAL:
        data = _SPECIAL[key]
    elif control and Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        data = bytes([key - Qt.Key.Key_A + 1])
    elif control and (text in {" ", "@"} or key == Qt.Key.Key_Space):
        data = b"\x00"
    elif control and key in {Qt.Key.Key_BracketLeft, Qt.Key.Key_Backslash, Qt.Key.Key_BracketRight}:
        data = bytes([{Qt.Key.Key_BracketLeft: 27, Qt.Key.Key_Backslash: 28, Qt.Key.Key_BracketRight: 29}[key]])
    else:
        data = text.encode("utf-8")
    return b"\x1b" + data if alt and data else data
