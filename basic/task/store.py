"""Machine-encrypted task files with support for older sequential workflows."""

import json
import re
from pathlib import Path

from common.configuration.codec import read_text, write_text
from common.i18n import tr

from .graph import graph_structure


TASK_SUFFIX = ".task.json"


class TaskStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve()

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

    def create(self, name: str, document: dict | None = None) -> None:
        document = {"version": 3, "steps": [], "links": [], "start_position": [20, 20]} if document is None else document
        self.validate(document)
        path = self.path_for(name)
        if path.exists():
            raise FileExistsError(tr("任务名称已存在：{0}", name))
        write_text(path, json.dumps(document, ensure_ascii=False, indent=2) + "\n", exclusive=True)

    def save(self, name: str, document: dict) -> None:
        self.validate(document)
        path = self.path_for(name)
        if not path.is_file():
            raise FileNotFoundError(tr("任务文件不存在：{0}", name))
        write_text(path, json.dumps(document, ensure_ascii=False, indent=2) + "\n")

    def rename(self, source: str, target: str) -> None:
        source_path, target_path = self.path_for(source), self.path_for(target)
        if target_path.exists() and target_path != source_path:
            raise FileExistsError(tr("任务名称已存在：{0}", target))
        source_path.rename(target_path)

    def copy(self, source: str, target: str) -> None:
        self.create(target, self.load(source))

    def delete(self, name: str) -> None:
        self.path_for(name).unlink()
