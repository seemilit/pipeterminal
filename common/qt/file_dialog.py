"""Local file and folder pickers with the system Desktop shortcut."""

from pathlib import Path

from PySide6.QtCore import QStandardPaths, QUrl
from PySide6.QtWidgets import QFileDialog


def _choose(parent, title, start, mode, name_filter="", *, save=False):
    dialog = QFileDialog(parent)
    try:
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog)
        dialog.setWindowTitle(title)
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave if save else QFileDialog.AcceptMode.AcceptOpen)
        dialog.setFileMode(mode)
        if mode == QFileDialog.FileMode.Directory:
            dialog.setOption(QFileDialog.Option.ShowDirsOnly)
        if name_filter:
            dialog.setNameFilter(name_filter)
        if start:
            if mode == QFileDialog.FileMode.Directory or Path(start).is_dir():
                dialog.setDirectory(start)
            else:
                dialog.selectFile(start)

        desktop = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        if desktop:
            url = QUrl.fromLocalFile(desktop)
            locations = dialog.sidebarUrls()
            if url not in locations:
                dialog.setSidebarUrls([*locations, url])

        if dialog.exec():
            return dialog.selectedFiles(), dialog.selectedNameFilter()
        return [], ""
    finally:
        dialog.deleteLater()


def choose_directory(parent, title, start=""):
    paths, _ = _choose(parent, title, start, QFileDialog.FileMode.Directory)
    return paths[0] if paths else ""


def choose_file(parent, title, start="", name_filter=""):
    paths, selected_filter = _choose(parent, title, start, QFileDialog.FileMode.ExistingFile, name_filter)
    return (paths[0] if paths else ""), selected_filter


def choose_files(parent, title, start="", name_filter=""):
    return _choose(parent, title, start, QFileDialog.FileMode.ExistingFiles, name_filter)


def choose_save_file(parent, title, start="", name_filter=""):
    paths, selected_filter = _choose(parent, title, start, QFileDialog.FileMode.AnyFile, name_filter, save=True)
    return (paths[0] if paths else ""), selected_filter
