"""File-type menu construction; no file I/O happens while opening a menu."""

import re
import sys
from dataclasses import dataclass

from PySide6.QtWidgets import QMenu

from common.i18n import tr


@dataclass(frozen=True)
class FileMenuContext:
    connection: object
    directory: str
    entries: tuple
    tree: bool = False


def build_remote_menu(parent, context, callback, *, enabled, can_paste, menu=None):
    if menu is None:
        menu = QMenu(parent)

    def add(label, action, available=True):
        item = menu.addAction(tr(label))
        item.setEnabled(enabled and available)
        item.triggered.connect(lambda _checked=False, value=action: callback(value, context))

    entries = context.entries
    if len(entries) == 1:
        entry = entries[0]
        if entry.directory:
            add("跳转目录", "open")
            add("粘贴到此文件夹", "paste_into", can_paste)
        else:
            add("打开文件编辑器", "edit", not entry.link)
            add("跳转目录", "parent")
            add("修改文件权限…", "chmod", not entry.link)
            if not entry.link and (entry.name.lower().endswith((".sh", ".bash", ".zsh")) or entry.mode & 0o111):
                add("执行脚本", "script")
                add("执行脚本并附带参数…", "script_args")
            if not entry.link and re.search(r"\.(log|out)(?:[.-][\w.-]+)?$", entry.name.lower()) and not entry.name.lower().endswith((".gz", ".bz2", ".xz", ".zip")):
                add("实时跟踪日志（tail -f）", "tail_follow")
                add("查看末尾 N 行…", "tail_lines")
                add("查询关键字…", "search")
        menu.addSeparator()
    if entries:
        concrete = all(entry.path.strip("/") for entry in entries)
        add("复制", "copy", concrete)
        if sys.platform == "win32":
            add("复制到 Windows 剪贴板", "copy_windows", concrete)
        add("剪切", "cut", concrete)
        add("复制路径", "copy_path")
        add("下载选中项", "download", concrete and all(not entry.link for entry in entries))
        add("重命名", "rename", len(entries) == 1 and concrete)
        add("删除…", "delete", concrete)
        return menu
    add("粘贴到当前目录", "paste", can_paste)
    add("新建文件…", "new_file")
    add("新建文件夹…", "new_directory")
    menu.addSeparator()
    add("上传文件…", "upload")
    add("上传文件夹…", "upload_folder")
    add("返回上级目录", "up")
    add("刷新", "refresh")
    return menu
