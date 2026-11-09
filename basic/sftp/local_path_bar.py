"""Local breadcrumb paths using the shared address-bar interaction."""

import os
from pathlib import Path

from .path_bar import RemotePathBar
from .path_menu import PathDirectoryMenu


class LocalPathDirectoryMenu(PathDirectoryMenu):
    def _current(self, context):
        return not self._closed

    def _read_folders(self, context, cancel, directory):
        folders = []
        with os.scandir(directory) as entries:
            for entry in entries:
                if cancel.is_set():
                    return ()
                try:
                    if entry.is_dir():
                        folders.append((entry.name, entry.path))
                except OSError:
                    continue
        return tuple(sorted(folders, key=lambda entry: entry[0].casefold()))


class LocalPathBar(RemotePathBar):
    def __init__(self, parent=None):
        super().__init__(parent, path_type=Path, directory_menu_factory=LocalPathDirectoryMenu)
