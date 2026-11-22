"""Headless checks for navigation across independently registered modules."""

import os
import unittest
from threading import Event

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, Qt, Signal, QObject
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from app.main_window import MainWindow
from basic.task.shell_panel import ShellPanelBridge
from common.modules.descriptor import ModuleDescriptor, WorkspaceDirectory
from common.modules.registry import ModuleRegistry
from common.qt.module_page import ModulePage


class _ConnectedSession(QObject):
    connected = Signal()
    disconnected = Signal(str)
    state = "connected"


class _DirectoryPage(ModulePage):
    def __init__(self, module_id, open_session):
        super().__init__()
        self.module_id = module_id
        self.open_session = open_session

    def open_workflow_shell(self, name, command="", *, directory=""):
        return self.open_session(self, name)


class _Panel(ModulePage):
    workspace_numbered = True

    def __init__(self, module_id, name):
        super().__init__()
        self.workspace_item_id = name
        self.setWindowTitle(name)
        self.fills_panel_workspace = module_id == "task"
        self.running = False
        if module_id == "connection":
            self.session = _ConnectedSession(self)

    def workspace_background_active(self):
        return self.running


class WorkspaceNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.registry = ModuleRegistry()
        self.directory = {"connection": ["server"], "task": ["workflow"], "extension": ["sample"]}
        self.reads = dict.fromkeys(self.directory, 0)
        self.created = []
        self.panels = []
        for order, module_id in enumerate(self.directory):
            self.registry.register(ModuleDescriptor(
                module_id, module_id, page_kind="home",
                page_factory=lambda key=module_id: self._create_page(key),
                workspace_directory=WorkspaceDirectory(
                    module_id, lambda key=module_id: self._read_directory(key), self._open_session, order,
                ),
            ))
        self.window = MainWindow(self.registry)
        self.window.resize(1190, 650)
        self.window.show()
        self.navigation = self.window.workspace

    def tearDown(self):
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def _create_page(self, module_id):
        self.created.append(module_id)
        return _DirectoryPage(module_id, self._open_session)

    def _read_directory(self, module_id):
        self.reads[module_id] += 1
        return list(self.directory[module_id])

    def _open_session(self, page, name):
        identifier = str(len(self.panels))
        panel = _Panel(page.module_id, name)
        panel.close_requested.connect(lambda: self.navigation.remove_session(identifier))
        self.panels.append(panel)
        page.bottom_panel_requested.emit(identifier, name, panel)
        return panel

    def _open(self, module_id):
        self.navigation._open_item(module_id, self.directory[module_id][0])

    def test_task_first_and_workflow_shell_activate_in_same_workspace(self):
        self._open("task")
        self.assertEqual(self.created, ["task"])
        task_panel = self.panels[0]
        task_panel.running = True
        request = {
            "cancel": Event(), "event": Event(),
            "properties": {"SERVER": "server", "WORKING_DIRECTORY": "/tmp", "SHELL_COMMAND": ""},
        }
        ShellPanelBridge(self.registry, self.window).open(request)
        self.assertTrue(request["event"].is_set())
        self.assertEqual(request["error"], "")
        self.assertEqual(self.navigation.active_session, "1")
        self.navigation.select_panel(task_panel)
        self.assertTrue(task_panel.running)
        self.assertEqual(self.navigation.active_session, "0")
        self.assertEqual(self.reads, dict.fromkeys(self.directory, 1))

    def test_shell_first_double_click_splits_and_restores_navigation(self):
        self._open("connection")
        self.assertEqual(self.created, ["connection"])
        tree = self.window.shell.sessions
        self.app.processEvents()
        point = tree.visualItemRect(self.navigation._items["connection", "server"]).center()
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=point)
        QTest.mouseDClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=point)
        QTest.qWait(QApplication.doubleClickInterval() + 50)
        self.assertEqual(len(self.panels), 2)
        self.assertEqual(self.navigation.sessions["1"].number, 2)
        first, second = self.panels
        bottom = self.window.shell.bottom_panel
        bottom._move_to_new_group(second)
        self.app.processEvents()
        bottom.splitter.setSizes([250, 660])
        sizes = bottom.splitter.sizes()
        self._open("task")
        self.app.processEvents()
        self.assertEqual(sum(size > 0 for size in bottom.splitter.sizes()), 1)
        self.navigation.select_panel(first)
        self.app.processEvents()
        self.assertEqual(bottom.splitter.sizes(), sizes)

    def test_background_identity_rename_and_registered_extension(self):
        self._open("connection")
        self._open("task")
        task_panel = self.panels[1]
        task_panel.running = True
        self.navigation.close_panel(task_panel)
        self.assertEqual(self.navigation.active_session, "0")
        self.assertTrue(self.navigation.sessions["1"].background)
        self.navigation.select_session("1")
        self.assertIs(self.navigation.sessions["1"].panel, task_panel)
        task_panel.running = False
        self.directory["task"] = ["renamed"]
        self.navigation.rename_item("task", "workflow", "renamed")
        self.assertEqual(task_panel.workspace_item_id, "renamed")
        self.assertEqual(task_panel.windowTitle(), "renamed")
        self._open("extension")
        self.assertEqual(self.navigation.active_session, "2")
        for panel in reversed(self.panels):
            self.navigation.close_panel(panel)
        self.assertIsNone(self.navigation.active_session)
        self.assertTrue(self.window.shell.workspace_mode)
        self.assertIn(("task", "renamed"), self.navigation._items)
        self.navigation._item_double_clicked(self.navigation._items["task", "renamed"], 0)
        self.assertIs(self.window.shell.tabs.currentWidget(), self.panels[-1])
        self.navigation.close_panel(self.panels[-1])
        tabs = self.window.shell.tabs
        QTest.mouseClick(tabs, Qt.MouseButton.LeftButton, pos=tabs.tabRect(0).center())
        self.assertFalse(self.window.shell.workspace_mode)

    def test_settings_button_opens_dialog_in_current_workspace(self):
        self.registry.register(ModuleDescriptor("settings", "Settings", page_factory=QDialog, page_kind="dialog"))
        self._open("task")
        self._open("connection")
        button = self.window.shell.workspace_settings_button
        self.assertFalse(button.isHidden())
        for index in (0, 1):
            self.navigation.select_panel(self.panels[index])
            button.click()
            dialog = self.window._module_pages["settings"]
            self.assertTrue(dialog.isVisible())
            self.assertTrue(self.window.shell.workspace_mode)
            self.assertEqual(self.navigation.active_session, str(index))
            self.assertIs(self.window.shell.tabs.currentWidget(), self.panels[index])
            dialog.close()
        self.assertEqual(len(self.navigation.sessions), 2)
