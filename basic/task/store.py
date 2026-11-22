"""Machine-encrypted task files with support for older sequential workflows."""

import json
import re
from pathlib import Path

from common.configuration.codec import read_text, write_text
from common.i18n import tr
from common.i18n.errors import error_message

from .graph import graph_structure


TASK_SUFFIX = ".task.json"


class TaskStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve()
        self.history_service = lambda: None
        self.last_history_error: str | None = None

    @staticmethod
    def resource_id(name: str) -> str:
        return "task:" + name

    def _snapshot(self, service, name: str, content: str, reason: str, *, required=False) -> None:
        if service is None:
            return
        try:
            service.snapshot(self.resource_id(name), content, reason)
        except (OSError, ValueError) as error:
            self.last_history_error = error_message(error)
            if required:
                raise

    def ensure_history(self, name: str) -> None:
        service = self.history_service()
        if service is not None:
            self._snapshot(service, name, read_text(self.path_for(name)), "当前版本", required=True)

    def path_for(self, name: str) -> Path:
        if (
            not name or name.strip() != name or name.rstrip(". ") != name
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            or re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", name.split(".")[0], re.IGNORECASE)
        ):
            raise ValueError(tr("文件名称包含 Windows 不允许的字符"))
        path = self.directory / f"{name}{TASK_SUFFIX}"
        if path.resolve().parent != self.directory or path.is_symlink():
            raise ValueError(tr("任务文件必须位于任务目录内"))
        return path

    def list_names(self) -> list[str]:
        if not self.directory.is_dir():
            return []
        return sorted(
            (path.name[:-len(TASK_SUFFIX)] for path in self.directory.glob(f"*{TASK_SUFFIX}")
             if path.is_file() and not path.is_symlink()),
            key=str.casefold,
        )

    @staticmethod
    def validate(document: dict) -> None:
        if (not isinstance(document, dict) or document.get("version") not in (2, 3)
                or not isinstance(document.get("steps"), list)):
            raise ValueError(tr("任务文件格式无效"))
        for step in document["steps"]:
            if (not isinstance(step, dict) or not isinstance(step.get("type"), str)
                    or not step["type"].strip() or not isinstance(step.get("properties", {}), dict)):
                raise ValueError(tr("任务文件格式无效"))

        if document["version"] == 3 or "links" in document:
            if "links" not in document:
                raise ValueError(tr("任务文件格式无效"))
            graph_structure(document)
        if "start_position" in document:
            position = document["start_position"]
            if not isinstance(position, list) or len(position) != 2 or not all(
                type(coordinate) in (int, float) and -1_000_000 <= coordinate <= 1_000_000
                for coordinate in position
            ):
                raise ValueError(tr("任务文件格式无效"))

    def load(self, name: str) -> dict:
        document = json.loads(read_text(self.path_for(name)))
        self.validate(document)
        return document

    def create(self, name: str, document: dict | None = None, *, reason: str = "新建") -> None:
        self.last_history_error = None
        document = {"version": 3, "steps": [], "links": [], "start_position": [20, 20]} if document is None else document
        self.validate(document)
        path = self.path_for(name)
        if path.exists():
            raise FileExistsError(tr("任务名称已存在：{0}", name))
        content = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        write_text(path, content, exclusive=True)
        self._snapshot(self.history_service(), name, content, reason)

    def save(self, name: str, document: dict, *, reason: str = "保存") -> None:
        self.last_history_error = None
        self.validate(document)
        service = self.history_service()
        restoring = reason == "回退"
        if restoring and (service is None or not service.allowed()):
            raise ValueError(tr("历史版本需要付费授权"))
        path = self.path_for(name)
        if not path.is_file():
            raise FileNotFoundError(tr("任务文件不存在：{0}", name))
        content = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        if service is not None:
            previous = read_text(path)
            if previous != content:
                self._snapshot(service, name, previous, "回退前" if restoring else "更新前", required=restoring)
        write_text(path, content)
        self._snapshot(service, name, content, reason)

    def rename(self, source: str, target: str) -> None:
        self.last_history_error = None
        source_path, target_path = self.path_for(source), self.path_for(target)
        if target_path.exists() and target_path != source_path:
            raise FileExistsError(tr("任务名称已存在：{0}", target))
        self.ensure_history(source)
        source_path.rename(target_path)
        service = self.history_service()
        if service is not None:
            try:
                service.rekey(self.resource_id(source), self.resource_id(target))
            except (OSError, ValueError) as error:
                self.last_history_error = error_message(error)

    def copy(self, source: str, target: str) -> None:
        self.create(target, self.load(source), reason="复制")

    def delete(self, name: str) -> None:
        self.last_history_error = None
        self.ensure_history(name)
        self.path_for(name).unlink()
