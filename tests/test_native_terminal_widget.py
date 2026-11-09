"""Headless drawing/input tests; no application startup or SSH traffic."""

import os
import sys
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from basic.terminal.input import encode_key
from basic.terminal.widget import NativeTerminalWidget


class NativeTerminalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.widget = NativeTerminalWidget()
        self.widget.resize(640, 240)
        self.widget.show()
        self.application.processEvents()
        self.widget.fit()
        self.sent = []
        self.widget.binaryCommitted.connect(self.sent.append)

    def tearDown(self):
        self.widget.shutdown()
        self.widget.close()
        self.widget.deleteLater()
        self.application.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_real_paint_and_color_does_not_change(self):
        self.widget.feed("ASCII 中文 é 👩‍💻\r\n\x1b[31mRED\x1b[0m".encode())
        self.widget.setFocus()
        before = self.widget.renderer.foreground.alpha()
        image = self.widget.viewport().grab().toImage()
        self.assertFalse(image.isNull())
        self.assertEqual(self.widget.renderer.foreground.alpha(), before)
        self.assertEqual(image.pixelColor(0, 0), self.widget.renderer.background)

    def test_keyboard_signals_without_execution(self):
        QTest.keyClick(self.widget, Qt.Key.Key_Return)
        QTest.keyClick(self.widget, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClick(self.widget, Qt.Key.Key_Up)
        self.assertEqual(self.sent, [b"\r", b"\x03", b"\x1b[A"])
        self.assertTrue(all(cell.text == " " for cell in self.widget.engine.screen.lines[0].cells))

    def test_ime_and_bracketed_paste(self):
        event = QInputMethodEvent()
        event.setCommitString("中文")
        self.application.sendEvent(self.widget, event)
        self.widget.feed(b"\x1b[?2004h")
        self.widget.paste("你好")
        self.assertEqual(self.sent, ["中文".encode(), b"\x1b[200~" + "你好".encode() + b"\x1b[201~"])

    def test_history_view_does_not_follow_new_output(self):
        self.widget.feed(b"line\r\n" * 40)
        bar = self.widget.verticalScrollBar()
        self.assertEqual(bar.value(), bar.maximum())
        bar.setValue(2)
        anchor = self.widget.engine.screen.row_at(bar.value()).id
        cursor = (self.widget.engine.cursor.row, self.widget.engine.cursor.col)
        self.widget.feed(b"next\r\n")
        self.assertEqual(self.widget.engine.screen.row_at(bar.value()).id, anchor)
        self.assertEqual(bar.value(), 2)
        self.assertEqual(cursor[0], self.widget.engine.cursor.row)

    def test_resize_reports_grid_dimensions(self):
        sizes = []
        self.widget.terminalResized.connect(lambda cols, rows: sizes.append((cols, rows)))
        self.widget.resize(800, 300)
        self.application.processEvents()
        self.widget.fit()
        self.assertTrue(sizes)
        self.assertEqual(sizes[-1], self.widget.terminal_size())

    def test_mouse_selection_and_clipboard(self):
        self.widget.feed("中文 test".encode())
        metrics = self.widget.renderer.metrics
        start = QPoint(metrics.padding + 1, metrics.padding + 2)
        end = QPoint(int(metrics.padding + metrics.width * 3), metrics.padding + 2)
        QTest.mousePress(self.widget.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(self.widget.viewport(), end)
        QTest.mouseRelease(self.widget.viewport(), Qt.MouseButton.LeftButton, pos=end)
        self.assertEqual(self.widget.selected_text(), "中文")
        self.widget.copy()
        self.assertEqual(self.application.clipboard().text(), "中文")

    def test_special_key_encodings(self):
        none = Qt.KeyboardModifier.NoModifier
        expected = {
            Qt.Key.Key_Backspace: b"\x7f", Qt.Key.Key_Tab: b"\t", Qt.Key.Key_Escape: b"\x1b",
            Qt.Key.Key_Home: b"\x1b[H", Qt.Key.Key_End: b"\x1b[F",
            Qt.Key.Key_PageUp: b"\x1b[5~", Qt.Key.Key_PageDown: b"\x1b[6~",
            Qt.Key.Key_Delete: b"\x1b[3~", Qt.Key.Key_Insert: b"\x1b[2~",
            Qt.Key.Key_F1: b"\x1bOP", Qt.Key.Key_F12: b"\x1b[24~",
        }
        for key, data in expected.items():
            self.assertEqual(encode_key(key, "", none), data)
        self.assertEqual(encode_key(Qt.Key.Key_D, "", Qt.KeyboardModifier.ControlModifier), b"\x04")
        self.assertEqual(encode_key(Qt.Key.Key_Z, "", Qt.KeyboardModifier.ControlModifier), b"\x1a")
        self.assertEqual(encode_key(Qt.Key.Key_Up, "", none, True), b"\x1bOA")

    def test_archived_native_adapter_has_no_browser(self):
        archived_app = str(Path(__file__).resolve().parents[2] / "ssh" / "app")
        sys.path.insert(0, archived_app)
        try:
            from qt_native_terminal import NativeTerminal
            adapter = NativeTerminal()
            events = []
            adapter.shellIdentified.connect(lambda *values: events.append(values))
            adapter.begin_directory_context()
            adapter.write("\x1b]777;DeployFlowShell;" + "a" * 32 + ";123;/tmp\x07test")
            self.assertEqual(events, [("a" * 32, 123, "/tmp", 1)])
            self.assertEqual(adapter.engine.screen.lines[0].cells[0].text, "t")
            self.assertFalse(any("QtWebEngine" in name or "QtWebChannel" in name for name in sys.modules))
            adapter.shutdown()
            adapter.deleteLater()
        finally:
            sys.path.remove(archived_app)


if __name__ == "__main__":
    unittest.main()
