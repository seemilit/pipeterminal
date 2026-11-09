"""Original-style system, resource, disk and process sidebar."""

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from common.i18n import tr
from common.i18n.widgets import QLabel, QProgressBar, QTreeWidget, QTreeWidgetItem

from .controller import MonitorController
from .model import SystemSnapshot, format_kib
from .process_actions import ProcessActions


class ServerStatusPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("serverStatusPanel")
        self.setMinimumWidth(220)
        self.setMaximumWidth(400)
        self._previous_cpu = None
        self._last_update = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        title = QLabel(tr("服务器状态"))
        title.setObjectName("monitorTitle")
        self._title_layout = QHBoxLayout()
        self._title_layout.setContentsMargins(0, 0, 0, 0)
        self._title_layout.addWidget(title, 1)
        layout.addLayout(self._title_layout)
        self.system = QLabel()
        self.kernel = QLabel()
        self.uptime = QLabel()
        self.load = QLabel()
        for label in (self.system, self.kernel, self.uptime, self.load):
            label.setWordWrap(True)
            layout.addWidget(label)
        self.cpu = QProgressBar()
        self.memory = QProgressBar()
        self.swap = QProgressBar()
        for progress in (self.cpu, self.memory, self.swap):
            progress.setRange(0, 100)
            progress.setFixedHeight(22)
            layout.addWidget(progress)
        disk_title = QLabel(tr("磁盘占用"))
        disk_title.setObjectName("monitorTitle")
        layout.addWidget(disk_title)
        self.disks = QTreeWidget()
        self.disks.setColumnCount(3)
        self.disks.setHeaderLabels([tr("挂载路径"), tr("已用 / 总量"), tr("占用")])
        self._configure_table(self.disks, (100, 105, 48))
        layout.addWidget(self.disks, 1)
        process_title = QLabel(tr("运行中的程序（资源占用前 12）"))
        process_title.setObjectName("monitorTitle")
        process_title.setWordWrap(True)
        layout.addWidget(process_title)
        self.processes = QTreeWidget()
        self.processes.setColumnCount(4)
        self.processes.setHeaderLabels([tr("服务"), tr("端口"), "CPU", tr("内存")])
        self._configure_table(self.processes, (112, 60, 42, 42))
        layout.addWidget(self.processes, 1)
        self.status = QLabel(tr("等待连接"))
        self.status.setObjectName("monitorStatus")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.controller = MonitorController(self)
        self.process_actions = ProcessActions(self)
        self.processes.setMouseTracking(True)
        self.processes.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.processes.customContextMenuRequested.connect(self.process_actions.show_menu)
        self.controller.snapshot_ready.connect(self._display)
        self.controller.snapshot_reset.connect(self._reset)
        self.controller.status_changed.connect(self._set_status)
        self._reset()

    @staticmethod
    def _configure_table(table, widths) -> None:
        table.setRootIsDecorated(False)
        table.setAlternatingRowColors(True)
        for column, width in enumerate(widths):
            table.setColumnWidth(column, width)

    def bind_session(self, session, log_service=None) -> None:
        self.controller.bind_session(session)
        self.process_actions.bind_session(session, log_service)

    def set_toggle_button(self, button) -> None:
        if self._title_layout.indexOf(button) < 0:
            self._title_layout.addWidget(button, 0, Qt.AlignmentFlag.AlignRight)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.controller.set_visible(True)

    def hideEvent(self, event) -> None:
        self.controller.set_visible(False)
        super().hideEvent(event)

    def shutdown(self) -> None:
        self.process_actions.shutdown()
        self.controller.shutdown()

    def _reset(self) -> None:
        self._previous_cpu = None
        self._last_update = None
        self.status.setToolTip("")
        self.system.setText(tr("操作系统：{0}", "--"))
        self.kernel.setText(tr("内核版本：{0}", "--"))
        self.uptime.setText(tr("运行时间：{0}", "--"))
        self.load.setText(tr("系统负载：{0}", "--"))
        for progress, text in (
            (self.cpu, tr("CPU：采集中")), (self.memory, tr("内存：--")), (self.swap, tr("交换区：--")),
        ):
            progress.setValue(0)
            progress.setFormat(text)
        self.disks.clear()
        self.processes.clear()

    def _display(self, snapshot: SystemSnapshot) -> None:
        self.system.setText(tr("操作系统：{0}", snapshot.system))
        self.kernel.setText(tr("内核版本：{0}", snapshot.kernel))
        if snapshot.uptime_seconds is None:
            uptime = "--"
        else:
            days, remainder = divmod(snapshot.uptime_seconds, 86400)
            hours, remainder = divmod(remainder, 3600)
            uptime = tr("{0} 天 {1} 小时 {2} 分钟", days, hours, remainder // 60)
        self.uptime.setText(tr("运行时间：{0}", uptime))
        self.load.setText(tr("系统负载：{0}", snapshot.load))
        percent = None
        if snapshot.cpu is not None and self._previous_cpu is not None:
            total = snapshot.cpu[0] - self._previous_cpu[0]
            idle = snapshot.cpu[1] - self._previous_cpu[1]
            if total > 0 and idle >= 0:
                percent = max(0, min(100, round((total - idle) * 100 / total)))
        self._previous_cpu = snapshot.cpu
        self.cpu.setValue(percent or 0)
        self.cpu.setFormat(tr("CPU：采集中") if percent is None else tr("CPU：{0}%", percent))
        self._set_usage(self.memory, snapshot.memory, "内存：{0}%  {1}/{2}", "内存：--")
        if snapshot.swap == (0, 0):
            self.swap.setValue(0)
            self.swap.setFormat(tr("交换区：未启用"))
        else:
            self._set_usage(self.swap, snapshot.swap, "交换区：{0}%  {1}/{2}", "交换区：--")
        self.disks.clear()
        for disk in snapshot.disks:
            self.disks.addTopLevelItem(QTreeWidgetItem([
                disk.mount, f"{format_kib(disk.used_kib)} / {format_kib(disk.total_kib)}", f"{disk.percent}%",
            ]))
        self._display_processes(snapshot.processes)
        self._last_update = datetime.now()
        if not self.process_actions.busy:
            self.status.setText(tr("自动更新：每 {0} 秒", self.controller.refresh_interval_seconds))
        self.status.setToolTip(tr("更新时间：{0}", self._last_update.strftime("%Y-%m-%d %H:%M:%S")))

    def _display_processes(self, processes) -> None:
        existing = {}
        for index in range(self.processes.topLevelItemCount()):
            item = self.processes.topLevelItem(index)
            process = item.data(0, Qt.ItemDataRole.UserRole)
            existing[(process.pid, process.start_time)] = item
        retained = set()
        for position, process in enumerate(processes):
            key = (process.pid, process.start_time)
            item = existing.get(key)
            if item is None:
                item = QTreeWidgetItem()
                self.processes.insertTopLevelItem(position, item)
            elif self.processes.indexOfTopLevelItem(item) != position:
                self.processes.takeTopLevelItem(self.processes.indexOfTopLevelItem(item))
                self.processes.insertTopLevelItem(position, item)
            retained.add(key)
            for column, text in enumerate((process.name, ", ".join(map(str, process.ports)) or "--",
                                           f"{process.cpu:g}%", f"{process.memory:g}%")):
                item.setText(column, text)
                item.setToolTip(column, tr("PID：{0}\n启动命令：{1}", process.pid, process.command))
            item.setData(0, Qt.ItemDataRole.UserRole, process)
        for key, item in existing.items():
            if key not in retained:
                self.processes.takeTopLevelItem(self.processes.indexOfTopLevelItem(item))

    def _set_status(self, message) -> None:
        if (self._last_update is not None or self.process_actions.busy) and getattr(message, "source", str(message)) == "正在采集…":
            return
        self.status.setText(message)

    @staticmethod
    def _set_usage(progress, value, pattern: str, unknown: str) -> None:
        if value is None or value[1] == 0:
            progress.setValue(0)
            progress.setFormat(tr(unknown))
        else:
            used, total = value
            percent = max(0, min(100, round(used * 100 / total)))
            progress.setValue(percent)
            progress.setFormat(tr(pattern, percent, format_kib(used), format_kib(total)))
