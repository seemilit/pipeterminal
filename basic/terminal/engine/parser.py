"""Incremental UTF-8 / ANSI framing, independent of any renderer."""

import codecs


class ANSIParser:
    def __init__(self, handler) -> None:
        self.handler = handler
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._state = "text"
        self._sequence = ""

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
                    self._sequence, self._state = "", "csi"
                elif char in "]P^_":
                    self._sequence, self._state = char, "string"
                elif char in "()*+":
                    self._state = "charset"
                else:
                    self._state = "text"
                    self.handler.escape(char)
            elif self._state == "charset":
                self.handler.charset(char)
                self._state = "text"
            elif self._state == "csi":
                if "@" <= char <= "~":
                    sequence = self._sequence
                    self._state = "text"
                    self.handler.csi(sequence, char)
                elif char == "\x1b":
                    self._state = "escape"
                elif char in "\x18\x1a":
                    self._state = "text"
                elif len(self._sequence) < 256:
                    self._sequence += char
                else:
                    self._state = "text"
            elif self._state == "string":
                if char == "\x07":
                    self._finish_string()
                elif char == "\x1b":
                    self._state = "string_escape"
                elif len(self._sequence) < 4096:
                    self._sequence += char
            elif self._state == "string_escape":
                if char == "\\":
                    self._finish_string()
                else:
                    self._state = "string"

    def _finish_string(self) -> None:
        sequence, self._sequence, self._state = self._sequence, "", "text"
        if sequence.startswith("]"):
            self.handler.osc(sequence[1:])
