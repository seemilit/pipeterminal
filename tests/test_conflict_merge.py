"""Focused merge tests: isolated Qt widgets and disposable local Git repositories."""

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication, QEvent, Qt, QPoint
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from basic.task.git.conflict_session import FileMerge
from basic.task.git.conflict_dialog import ConflictDialog
from basic.task.git.merge_assist import simple_merge
from basic.task.git.merge import GitMergePush, GitMergeError
from common.i18n.widgets import QDialog


def item(path="sample.py", base="x = 1\n", left="x = 2\n", right="x = 3\n", prefix="start\n", suffix="end\n"):
    stage = lambda text: dict(text=text, oid=text, mode="100644")
    return dict(path=path, text=True, result=prefix + "<<<<<<< L\n" + left + "||||||| base\n" + base + "=======\n" + right + ">>>>>>> R\n" + suffix,
                stages={1: stage(prefix + base + suffix), 2: stage(prefix + left + suffix), 3: stage(prefix + right + suffix)})


class ModelTests(unittest.TestCase):
    def test_independent_decisions_and_history(self):
        draft = FileMerge(item())
        draft.accept_side(0, "left")
        self.assertEqual(draft.remaining, 1)
        draft.ignore(0, "right")
        self.assertEqual(draft.remaining, 0)
        self.assertTrue(draft.apply())
        draft.restore(-1)
        self.assertIsNone(draft.resolution)
        draft.restore(-1)
        self.assertEqual(draft.remaining, 1)
        draft.restore(1)
        self.assertEqual(draft.remaining, 0)

    def test_manual_edit_requires_confirmation(self):
        draft = FileMerge(item())
        draft.edit(draft.text.replace("x = 1", "x = 4"))
        self.assertFalse(draft.apply())
        draft.mark_manual(0)
        self.assertTrue(draft.apply())

    def test_reset_and_both_ignored(self):
        draft = FileMerge(item())
        initial = draft.text
        draft.ignore(0, "left")
        draft.ignore(0, "right")
        self.assertEqual(draft.text, initial)
        self.assertTrue(draft.apply())
        draft.reset()
        self.assertIsNone(draft.resolution)
        self.assertEqual(draft.remaining, 1)

    def test_suggestion_disjoint_edits(self):
        self.assertEqual(simple_merge("x=1; y=2\n", "x=3; y=2\n", "x=1; y=4\n"), "x=3; y=4\n")

    def test_suggestion_rejects_overlap_and_large_input(self):
        self.assertIsNone(simple_merge("x=1", "x=2", "x=3"))
        self.assertIsNone(simple_merge("ab", "aXb", "aYb"))
        self.assertIsNone(simple_merge("a" * 4001, "b", "c"))


class EditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls.app.clipboard().clear()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def setUp(self):
        self.errors = []
        self.old_hook = sys.excepthook
        sys.excepthook = lambda _type, error, _tb: self.errors.append(str(error))
        self.dialog = ConflictDialog(dict(files=[item(), item("other.py")], left="main", right="feature"))
        self.dialog.show()
        self.dialog._open_editor()
        self.editor = self.dialog._editors["sample.py"]
        self.wait(self.editor)

    def wait(self, editor):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self.app.processEvents()
            if editor._mapping_revision == editor._revision and not editor._mapping_busy and not editor._timer.isActive():
                break
            QTest.qWait(10)
        self.assertEqual(editor._mapping_revision, editor._revision)
        self.assertFalse(self.errors, self.errors)

    def tearDown(self):
        for editor in self.dialog._editors.values():
            self.wait(editor)
        self.dialog.reject()
        self.dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        sys.excepthook = self.old_hook
        self.assertFalse(self.errors, self.errors)

    def test_no_padding_in_text_or_clipboard(self):
        self.assertEqual(self.editor.result.toPlainText(), self.editor.draft.text)
        self.editor.result.selectAll()
        self.editor.result.copy()
        self.assertEqual(self.app.clipboard().text(), self.editor.draft.text)
        self.assertFalse(self.app.clipboard().mimeData().hasHtml())

    def test_display_options_do_not_modify_draft(self):
        original = self.editor.draft.text
        history = len(self.editor.draft.history)
        self.editor.ignore_space.setChecked(True)
        self.editor.highlight_mode.setCurrentIndex(1)
        self.wait(self.editor)
        self.assertEqual(self.editor.draft.text, original)
        self.assertEqual(len(self.editor.draft.history), history)
        self.assertFalse(any(entry[3] == "character" for pane in self.editor._decorations for entry in pane))

    def test_undo_redo_and_apply_next(self):
        self.editor._change(0, "left")
        self.wait(self.editor)
        self.editor.result.setFocus()
        QTest.keyClick(self.editor.result, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        self.wait(self.editor)
        self.assertEqual(self.editor.draft.remaining, 1)
        self.editor._history(1)
        self.wait(self.editor)
        self.assertEqual(self.editor.draft.remaining, 0)
        self.editor.next_file.setChecked(True)
        self.editor._apply()
        self.assertIn("sample.py", self.dialog.resolutions)
        self.assertIn("other.py", self.dialog._editors)
        self.assertTrue(self.dialog._editors["other.py"].isVisible())

    def test_cancel_and_close_are_distinct(self):
        finished = []
        self.dialog.finished.connect(finished.append)
        self.dialog.close()
        self.assertEqual(finished, [])
        self.assertFalse(self.editor.isVisible())
        self.dialog.show()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.dialog._cancel()
        self.assertEqual(len(finished), 1)
        self.assertEqual(finished[0], 0)

    def test_syntax_formats_overview_and_connections(self):
        self.assertTrue(any(block.layout().formats() for block in self.blocks(self.editor.result.document())))
        self.assertTrue(self.editor.overview.markers)
        self.assertTrue(any(lane.bands for lane in self.editor.lanes))
        self.editor.overview.resize(16, 300)
        QTest.mouseClick(self.editor.overview, Qt.MouseButton.LeftButton, pos=QPoint(8, 90))
        self.assertIsNotNone(self.editor._current_block())

    def test_unequal_blocks_align_and_unicode_survives(self):
        draft = FileMerge(item(base="x=1\n", left="x=2\na=3\nb=4\n", right="x=5\n", prefix="# 中文😀\nx = 'a\u00a0b'\n"))
        self.editor.draft = draft
        self.editor.reload()
        self.wait(self.editor)
        self.assertEqual(self.editor.result.toPlainText(), draft.text)
        positions = []
        for editor in self.editor.editors:
            block = next(block for block in self.blocks(editor.document()) if block.text() == "end")
            positions.append(editor.cursorRect(QTextCursor(block)).top())
        self.assertLessEqual(max(positions) - min(positions), 2)
        self.editor._change(0, "both")
        self.wait(self.editor)
        self.assertIn("a\u00a0b", self.editor.draft.text)

    def test_suggestion_requires_confirmation_and_ignores_stale_result(self):
        before = self.editor.draft.text
        with patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Rejected):
            self.editor._show_suggestion(self.editor._revision, 0, "x = 4\n")
        self.assertEqual(self.editor.draft.text, before)
        self.editor._show_suggestion(self.editor._revision - 1, 0, "stale\n")
        self.assertEqual(self.editor.draft.text, before)
        with patch.object(QDialog, "exec", return_value=QDialog.DialogCode.Accepted):
            self.editor._show_suggestion(self.editor._revision, 0, "x = 4\n")
        self.wait(self.editor)
        self.assertIn("x = 4", self.editor.draft.text)
        self.assertEqual(self.editor.draft.remaining, 0)
        self.editor._history(-1)
        self.wait(self.editor)
        self.assertEqual(self.editor.draft.text, before)

    def test_restore_conflicts_after_whole_file_selection(self):
        self.dialog._choose("right")
        self.wait(self.editor)
        self.assertIn("sample.py", self.dialog.resolutions)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.dialog._reset_selected()
        self.wait(self.editor)
        self.assertNotIn("sample.py", self.dialog.resolutions)
        self.assertEqual(self.editor.draft.remaining, 1)

    @staticmethod
    def blocks(document):
        block = document.begin()
        while block.isValid():
            yield block
            block = block.next()


class GitCancellationTests(unittest.TestCase):
    def test_cancel_preserves_local_and_remote_repositories(self):
        with tempfile.TemporaryDirectory(prefix="pipeterminal-merge-test-", ignore_cleanup_errors=True) as directory:
            root = Path(directory).resolve()
            self.assertTrue(root.is_relative_to(Path(tempfile.gettempdir()).resolve()))
            environment = os.environ.copy()
            environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
            def git(where, *args):
                return subprocess.run(["git", "-C", str(where), *args], env=environment, check=True, capture_output=True, text=True, encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
            bare, target, source = root/"remote.git", root/"target", root/"source"
            git(root, "init", "--bare", str(bare))
            git(root, "init", "-b", "main", str(target))
            for key, value in (("user.name", "Merge Test"), ("user.email", "merge@example.invalid"), ("commit.gpgsign", "false"), ("core.autocrlf", "false")):
                git(target, "config", key, value)
            (target/"file.txt").write_text("base\n", encoding="utf-8")
            git(target, "add", "file.txt"); git(target, "commit", "-m", "base")
            git(target, "remote", "add", "origin", str(bare)); git(target, "push", "-u", "origin", "main")
            git(root, "clone", "-b", "main", str(bare), str(source))
            for key, value in (("user.name", "Merge Test"), ("user.email", "merge@example.invalid"), ("commit.gpgsign", "false"), ("core.autocrlf", "false")):
                git(source, "config", key, value)
            git(source, "switch", "-c", "feature")
            (source/"file.txt").write_text("source\n", encoding="utf-8")
            git(source, "commit", "-am", "source")
            (target/"file.txt").write_text("target\n", encoding="utf-8")
            git(target, "commit", "-am", "target"); git(target, "push")
            before = (git(source, "rev-parse", "HEAD"), git(target, "rev-parse", "HEAD"), git(bare, "rev-parse", "main"))
            (target/"local.txt").write_text("keep", encoding="utf-8")
            calls = []
            def cancel(request):
                calls.append(request)
                self.assertIn("|||||||", request["files"][0]["result"])
                return None
            with patch.dict(os.environ, environment, clear=True):
                with self.assertRaises(GitMergeError):
                    GitMergePush(lambda message: None, cancel).execute(dict(SOURCE_PROJECT_PATH=str(source), SOURCE_BRANCH="feature", TARGET_PROJECT_PATH=str(target), TARGET_BRANCH="main", CONFLICT_POLICY="merge"))
            self.assertEqual(len(calls), 1)
            self.assertEqual(before, (git(source, "rev-parse", "HEAD"), git(target, "rev-parse", "HEAD"), git(bare, "rev-parse", "main")))
            self.assertEqual((target/"local.txt").read_text(), "keep")
            self.assertEqual((target/"file.txt").read_text(), "target\n")
            with patch.dict(os.environ, environment, clear=True):
                GitMergePush(lambda message: None, lambda request: {entry["path"]: ("right", None) for entry in request["files"]}).execute(dict(SOURCE_PROJECT_PATH=str(source), SOURCE_BRANCH="feature", TARGET_PROJECT_PATH=str(target), TARGET_BRANCH="main", CONFLICT_POLICY="merge"))
            self.assertEqual(git(bare, "show", "main:file.txt"), "source")
            self.assertEqual(before[:2], (git(source, "rev-parse", "HEAD"), git(target, "rev-parse", "HEAD")))
            self.assertEqual((target/"local.txt").read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
