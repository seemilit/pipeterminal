"""Encrypted workflow execution summaries with links to existing session logs."""
import json
import math
from collections import OrderedDict
from copy import deepcopy
from threading import Condition, Thread
from datetime import datetime
from pathlib import Path
from time import time
from uuid import uuid4
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QSplitter, QVBoxLayout
from basic.log.viewer import LogViewer
from common.configuration.codec import read_text, write_text
from common.i18n import tr
from common.i18n.widgets import QDialog, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem

STATES = {"running": "正在执行", "waiting": "等待执行", "success": "执行成功", "failed": "执行失败", "stopped": "已停止", "pending": "尚未执行", "unfinished": "未结束"}


class RunHistoryStore:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.failed_reads = 0

    def create(self, name, steps, log_path):
        now = time()
        record = {"id": uuid4().hex, "task": name, "started": now, "finished": None, "state": "running", "message": "", "log": str(log_path), "steps": [{"type": step["type"], "state": "pending", "started": None, "finished": None} for step in steps]}
        return record

    def save(self, record):
        identifier = record["id"]
        if len(identifier) != 32 or any(char not in "0123456789abcdef" for char in identifier):
            raise ValueError(tr("任务文件格式无效"))
        write_text(self.directory / (identifier + ".run.json"), json.dumps(record, ensure_ascii=False))

    @staticmethod
    def validate_record(record):
        if not isinstance(record, dict):
            raise ValueError("Invalid history record")
        for key in ("id", "task", "state", "message", "log"):
            if not isinstance(record.get(key), str):
                raise ValueError("Invalid history record")
        if type(record.get("_revision", 0)) is not int or record.get("_revision", 0) < 0:
            raise ValueError("Invalid history record")
        if len(record["id"]) != 32 or any(char not in "0123456789abcdef" for char in record["id"]) or record["state"] not in STATES:
            raise ValueError("Invalid history record")
        def timestamp(value, optional=False):
            return (optional and value is None) or (type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 253402214400)
        if not timestamp(record.get("started")) or not timestamp(record.get("finished"), True) or not isinstance(record.get("steps"), list):
            raise ValueError("Invalid history record")
        for step in record["steps"]:
            if not isinstance(step, dict) or not isinstance(step.get("type"), str) or step.get("state") not in STATES:
                raise ValueError("Invalid history record")
            if not timestamp(step.get("started"), True) or not timestamp(step.get("finished"), True) or (step.get("finished") is not None and step.get("started") is None):
                raise ValueError("Invalid history record")
        return record

    def records(self):
        self.failed_reads = 0
        if not self.directory.exists():
            return []
        paths = []
        for path in self.directory.glob("*.run.json"):
            try:
                if path.is_symlink() or path.resolve().parent != self.directory:
                    continue
                paths.append((path.stat().st_mtime, path))
            except OSError:
                self.failed_reads += 1
        records = []
        for _modified, path in sorted(paths, reverse=True):
            try:
                record = self.validate_record(json.loads(read_text(path)))
            except (OSError, ValueError, TypeError, KeyError, OverflowError):
                self.failed_reads += 1
                continue
            records.append(record)
            if len(records) >= 200:
                break
        return records


class RunHistoryWriter(QObject):
    failed = Signal(str, str)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self._condition = Condition()
        self._pending = OrderedDict()
        self._inflight = None
        self._finalized = set()
        self._sequence = 0
        self._closing = False
        self._thread = Thread(target=self._run, name="task-history-writer", daemon=True)
        self._thread.start()

    def submit(self, record):
        snapshot = deepcopy(record)
        identifier = snapshot["id"]
        with self._condition:
            if self._closing:
                raise ValueError(tr("执行记录保存线程已关闭"))
            if identifier in self._finalized:
                return
            if snapshot.get("finished") is not None:
                self._finalized.add(identifier)
            self._sequence += 1
            snapshot["_revision"] = self._sequence
            self._pending[identifier] = snapshot
            self._condition.notify()

    def snapshot(self):
        with self._condition:
            records = {self._inflight["id"]: self._inflight} if self._inflight else {}
            records.update(self._pending)
            return deepcopy(list(records.values()))

    def close(self):
        with self._condition:
            self._closing = True
            self._condition.notify_all()
        self._thread.join(timeout=5)
        return not self._thread.is_alive()

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._pending or self._closing)
                if not self._pending:
                    return
                identifier = next((key for key, value in self._pending.items() if value.get("finished") is not None), next(iter(self._pending)))
                record = self._pending.pop(identifier)
                self._inflight = record
            try:
                self.store.save(record)
            except Exception as error:
                try:
                    self.failed.emit(identifier, str(error))
                except RuntimeError:
                    pass
            finally:
                with self._condition:
                    self._inflight = None


class RunHistoryDialog(QDialog):
    def __init__(self, store, labels, log_roots, active_id=None, parent=None, pending=()):
        super().__init__(parent)
        self.setWindowTitle(tr("执行记录"))
        self.resize(1050, 700)
        self.labels, self.log_roots = labels, [Path(root).resolve() for root in log_roots]
        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Vertical)
        self.runs = QTreeWidget()
        self.runs.setRootIsDecorated(False)
        self.runs.setHeaderLabels([tr("任务"), tr("开始时间"), tr("状态"), tr("耗时（秒）")])
        self.runs.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        splitter.addWidget(self.runs)
        self.steps = QTreeWidget()
        self.steps.setRootIsDecorated(False)
        self.steps.setHeaderLabels([tr("流程"), tr("状态"), tr("耗时（秒）")])
        splitter.addWidget(self.steps)
        log_viewer = LogViewer(self)
        self.details = log_viewer.text
        self.details.setMaximumBlockCount(10000)
        splitter.addWidget(log_viewer)
        splitter.setSizes([220, 160, 300])
        layout.addWidget(splitter, 1)
        close = QPushButton(tr("关闭"))
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("显示最近 200 次执行记录；日志显示末尾 4 MiB。")))
        row.addStretch()
        row.addWidget(close)
        layout.addLayout(row)
        records = {record["id"]: record for record in store.records()}
        for record in pending:
            existing = records.get(record["id"])
            if existing is None or record.get("_revision", 0) >= existing.get("_revision", 0):
                records[record["id"]] = record
        if store.failed_reads:
            warning = QLabel(tr("有 {0} 条执行记录读取失败，已跳过；原文件已保留。", store.failed_reads))
            warning.setWordWrap(True)
            layout.insertWidget(0, warning)
        for record in sorted(records.values(), key=lambda item: item["started"], reverse=True)[:200]:
            state = record["state"]
            if state == "running" and record["id"] != active_id:
                state = "unfinished"
            if state == "unfinished":
                for step in record["steps"]:
                    if step["state"] in {"running", "waiting"}:
                        step["state"] = "unfinished"
            elapsed = (record["finished"] or time()) - record["started"] if state != "unfinished" else None
            item = QTreeWidgetItem([record["task"], datetime.fromtimestamp(record["started"]).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3], str(tr(STATES.get(state, state))), f"{elapsed:.3f}" if elapsed is not None else "--"])
            item.setData(0, Qt.ItemDataRole.UserRole, record)
            self.runs.addTopLevelItem(item)
        self.runs.currentItemChanged.connect(self._select)
        if self.runs.topLevelItemCount():
            self.runs.setCurrentItem(self.runs.topLevelItem(0))
        else:
            self.details.setPlainText(str(tr("暂无执行记录")))

    def _select(self, item, _previous):
        if item is None:
            return
        record = item.data(0, Qt.ItemDataRole.UserRole)
        self.steps.clear()
        for index, step in enumerate(record["steps"], 1):
            elapsed = step["finished"] - step["started"] if step.get("finished") and step.get("started") else None
            self.steps.addTopLevelItem(QTreeWidgetItem([str(tr("{0}. {1}", index, tr(self.labels.get(step["type"], step["type"])))), str(tr(STATES.get(step["state"], step["state"]))), f"{elapsed:.3f}" if elapsed is not None else "--"]))
        text = record.get("message", "")
        try:
            path = Path(record["log"]).resolve()
            if not any(path.is_relative_to(root) for root in self.log_roots) or path.suffix != ".log":
                raise ValueError(tr("日志路径必须位于日志目录内"))
            with path.open("rb") as handle:
                size = handle.seek(0, 2)
                handle.seek(max(0, size - 4 * 1024 * 1024))
                text += "\n\n" + handle.read(4 * 1024 * 1024).decode("utf-8", "replace")
        except (OSError, ValueError) as error:
            text += "\n" + str(error)
        self.details.setPlainText(text)
