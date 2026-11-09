"""Offline terminal state tests; no server or persistent configuration data."""

import unittest

from basic.terminal.engine import TerminalEngine


def text(engine, row=0):
    return "".join(cell.text for cell in engine.screen.lines[row].cells if not cell.continuation).rstrip()


class TerminalEngineTests(unittest.TestCase):
    def test_fragmented_utf8_and_control_characters(self):
        engine = TerminalEngine(4, 20)
        data = "中文".encode()
        for byte in data:
            engine.feed(bytes([byte]))
        self.assertEqual(text(engine), "中文")
        self.assertEqual(engine.cursor.col, 4)
        engine.feed(b"\rA\tB\bC\r\nD")
        self.assertEqual(engine.screen.lines[0].cells[8].text, "C")
        self.assertEqual(text(engine, 1), "D")

    def test_fragmented_csi_and_all_cell_attributes(self):
        engine = TerminalEngine(4, 20)
        for chunk in (b"\x1b[1;3", b";4;7;31;44", b"mA\x1b[0mB"):
            engine.feed(chunk)
        first, second = engine.screen.lines[0].cells[:2]
        self.assertTrue(first.bold and first.italic and first.underline and first.inverse)
        self.assertEqual((first.foreground, first.background), (1, 4))
        self.assertFalse(second.bold or second.italic or second.underline or second.inverse)
        self.assertIsNone(second.foreground)

    def test_colors_16_256_and_true_color(self):
        engine = TerminalEngine()
        engine.feed(b"\x1b[91;104mA\x1b[38;5;200;48;5;17mB\x1b[38;2;1;2;3mC")
        a, b, c = engine.screen.lines[0].cells[:3]
        self.assertEqual((a.foreground, a.background), (9, 12))
        self.assertEqual((b.foreground, b.background), (200, 17))
        self.assertEqual(c.foreground, (1, 2, 3))

    def test_cursor_position_and_erase(self):
        engine = TerminalEngine(4, 20)
        engine.feed(b"abcde\x1b[1;3H\x1b[K")
        self.assertEqual(text(engine), "ab")
        engine.feed(b"\x1b[3;4HX\x1b[2J")
        self.assertEqual((engine.cursor.row, engine.cursor.col), (2, 4))
        self.assertTrue(all(not text(engine, row) for row in range(4)))

    def test_wide_cells_and_overwrite_continuation(self):
        engine = TerminalEngine(4, 20)
        engine.feed("中A".encode())
        self.assertEqual(engine.screen.lines[0].cells[0].width, 2)
        self.assertTrue(engine.screen.lines[0].cells[1].continuation)
        engine.feed(b"\x1b[1;2HX")
        self.assertEqual(text(engine), " XA")
        self.assertFalse(any(cell.continuation for cell in engine.screen.lines[0].cells))

    def test_combining_and_emoji_clusters(self):
        engine = TerminalEngine(4, 40)
        engine.feed("e\u0301❤\ufe0f👩\u200d💻🇨🇳👍🏽A".encode())
        heads = [cell for cell in engine.screen.lines[0].cells if not cell.continuation and cell.text != " "]
        self.assertEqual([cell.text for cell in heads], ["é", "❤️", "👩‍💻", "🇨🇳", "👍🏽", "A"])
        self.assertEqual([cell.width for cell in heads], [1, 2, 2, 2, 2, 1])
        self.assertEqual(engine.cursor.col, 10)

    def test_wide_character_wrap_and_selection(self):
        engine = TerminalEngine(3, 5)
        engine.feed("abcd中X".encode())
        self.assertEqual(text(engine), "abcd")
        self.assertEqual(text(engine, 1), "中X")
        start, end = engine.screen.lines[:2]
        self.assertEqual(engine.screen.selected_text((start.id, 0), (end.id, 2)), "abcd中X")
        self.assertEqual(engine.screen.selected_text((end.id, 1), (end.id, 1)), "中")

    def test_bounded_scrollback_and_line_identity(self):
        engine = TerminalEngine(2, 20, 3)
        engine.feed(b"one\r\ntwo\r\nthree\r\nfour\r\nfive\r\nsix")
        self.assertEqual(len(engine.screen.history), 3)
        self.assertEqual(["".join(cell.text for cell in line.cells).rstrip() for line in engine.screen.history], ["two", "three", "four"])
        self.assertEqual((text(engine), text(engine, 1)), ("five", "six"))
        self.assertEqual(len({line.id for line in [*engine.screen.history, *engine.screen.lines]}), 5)

    def test_clear_history_does_not_clear_visible_screen(self):
        engine = TerminalEngine(2, 20)
        engine.feed(b"history\r\nvisible\r\nlast")
        engine.feed(b"\x1b[3J")
        self.assertFalse(engine.screen.history)
        self.assertEqual((text(engine), text(engine, 1)), ("visible", "last"))

    def test_resize_cleans_wide_boundaries(self):
        engine = TerminalEngine(4, 10)
        engine.feed("1234中".encode())
        engine.resize(3, 5)
        self.assertEqual(text(engine), "1234")
        self.assertEqual(len(engine.screen.lines), 3)
        self.assertTrue(all(len(line.cells) == 5 for line in engine.screen.lines))

    def test_insert_delete_characters(self):
        engine = TerminalEngine(4, 20)
        engine.feed(b"abcde\r\x1b[2C\x1b[@")
        self.assertEqual(text(engine), "ab cde")
        engine.feed(b"\x1b[P")
        self.assertEqual(text(engine), "abcde")

    def test_scroll_region_does_not_enter_history(self):
        engine = TerminalEngine(4, 20)
        engine.feed(b"a\r\nb\r\nc\r\nd\x1b[2;3r\x1b[3;1H\n")
        self.assertEqual((text(engine, 0), text(engine, 1), text(engine, 2), text(engine, 3)), ("a", "c", "", "d"))
        self.assertFalse(engine.screen.history)

    def test_alternate_screen_and_protocol_queries(self):
        engine = TerminalEngine(4, 20)
        engine.feed(b"shell\x1b[?1049hAPP\x1b[?25l")
        self.assertEqual(text(engine), "APP")
        self.assertFalse(engine.cursor.visible)
        engine.feed(b"\x1b[?1049l\x1b[6n")
        self.assertEqual(text(engine), "shell")
        self.assertEqual(engine.take_responses(), b"\x1b[1;6R")
        self.assertTrue(engine.cursor.visible)

    def test_osc_and_dcs_are_not_drawn(self):
        engine = TerminalEngine()
        engine.feed(b"A\x1b]0;title\x07B\x1bPignored\x1b\\C")
        self.assertEqual(text(engine), "ABC")
        self.assertEqual(engine.take_events(), [("osc", "0;title")])

    def test_damage_records_only_changed_lines(self):
        engine = TerminalEngine(4, 20)
        engine.screen.take_damage()
        engine.feed(b"abc")
        damage = engine.screen.take_damage()
        self.assertFalse(damage.full)
        self.assertEqual(damage.line_ids, frozenset({engine.screen.lines[0].id}))
        self.assertFalse(engine.screen.take_damage().line_ids)

    def test_every_byte_fragment_preserves_state(self):
        data = "a中é\x1b[31mred\x1b[0m\r\n👩‍💻\x1b[2D!".encode()
        one, many = TerminalEngine(4, 20), TerminalEngine(4, 20)
        one.feed(data)
        for byte in data:
            many.feed(bytes([byte]))
        self.assertEqual([line.cells for line in one.screen.lines], [line.cells for line in many.screen.lines])
        self.assertEqual(one.cursor, many.cursor)


if __name__ == "__main__":
    unittest.main()
