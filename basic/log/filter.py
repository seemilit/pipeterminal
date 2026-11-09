"""Incremental UTF-8 text filtering for logs, without a terminal dependency."""

import codecs


class OutputFilter:
    def __init__(self, handler) -> None:
        self.handler = handler
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._state = "text"

    def feed(self, data: bytes, final: bool = False) -> None:
        for char in self._decoder.decode(data, final=final):
            if self._state == "text":
                if char == "\x1b":
                    self._state = "escape"
                elif ord(char) < 32 or char == "\x7f":
                    self.handler.control(char)
                else:
                    self.handler.draw(char)
            elif self._state == "escape":
                if char == "[":
                    self._state = "csi"
                elif char in "]P^_":
                    self._state = "string"
                elif char in "()*+":
                    self._state = "charset"
                else:
                    self._state = "text"
            elif self._state == "charset":
                self._state = "text"
            elif self._state == "csi":
                if "@" <= char <= "~" or char in "\x18\x1a":
                    self._state = "text"
                elif char == "\x1b":
                    self._state = "escape"
            elif self._state == "string":
                if char in "\x07\x18\x1a":
                    self._state = "text"
                elif char == "\x1b":
                    self._state = "string_escape"
            elif self._state == "string_escape":
                self._state = "text" if char == "\\" else "string"
