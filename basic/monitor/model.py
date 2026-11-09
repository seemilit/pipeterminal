"""UI-independent parsing of bounded monitor snapshots."""

import math
import posixpath
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DiskUsage:
    mount: str
    used_kib: int
    total_kib: int
    percent: int


@dataclass(frozen=True)
class ProcessUsage:
    pid: int
    name: str
    command: str
    cpu: float
    memory: float
    ports: tuple[int, ...]
    start_time: str = ""


@dataclass(frozen=True)
class SystemSnapshot:
    system: str
    kernel: str
    uptime_seconds: int | None
    load: str
    cpu: tuple[int, int] | None
    memory: tuple[int, int] | None
    swap: tuple[int, int] | None
    disks: tuple[DiskUsage, ...]
    processes: tuple[ProcessUsage, ...]


def parse_snapshot(text: str) -> SystemSnapshot:
    system, kernel, load = "--", "--", "--"
    uptime, cpu = None, None
    memory, disks, processes, ports = {}, [], [], {}
    section = "system"
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line in {"DF_BEGIN", "PS_BEGIN", "PORT_BEGIN"}:
            section = line
            continue
        try:
            if section == "DF_BEGIN":
                fields = line.split(maxsplit=5)
                if len(fields) == 6 and fields[1].isdigit():
                    total, used = int(fields[1]), int(fields[2])
                    percent = int(fields[4].rstrip("%"))
                    disks.append(DiskUsage(fields[5].replace(r"\040", " "), used, total, percent))
            elif section == "PS_BEGIN":
                start_time = ""
                if line.startswith("PT_PROCESS "):
                    _marker, start_time, line = line.split(" ", 2)
                    if not start_time.isascii() or not start_time.isdigit():
                        continue
                fields = line.split(maxsplit=4)
                if len(fields) >= 4 and len(processes) < 12:
                    pid, cpu_value, memory_value = int(fields[0]), float(fields[1]), float(fields[2])
                    if pid > 0 and math.isfinite(cpu_value) and math.isfinite(memory_value):
                        command = fields[4] if len(fields) == 5 else fields[3]
                        processes.append((pid, process_name(fields[3], command), command, cpu_value, memory_value, start_time))
            elif section == "PORT_BEGIN":
                fields = line.split()
                if len(fields) >= 5:
                    local_port = fields[4].rsplit(":", 1)[-1]
                    if local_port.isdigit():
                        for pid in re.findall(r"pid=(\d+)", line):
                            ports.setdefault(int(pid), set()).add(int(local_port))
            elif line.startswith("SYSTEM "):
                system = line[7:] or "--"
            elif line.startswith("KERNEL "):
                kernel = line[7:] or "--"
            elif line.startswith("UPTIME "):
                uptime = max(0, int(float(line[7:])))
            elif line.startswith("LOAD "):
                load = line[5:]
            elif line.startswith("cpu "):
                values = [int(value) for value in line.split()[1:9]]
                if len(values) >= 4:
                    cpu = sum(values), values[3] + (values[4] if len(values) > 4 else 0)
            elif ":" in line:
                key, value = line.split(":", 1)
                memory[key] = max(0, int(value.split()[0]))
        except (ValueError, IndexError, OverflowError):
            continue
    if cpu is None or "MemTotal" not in memory:
        raise ValueError("PT_MONITOR_UNSUPPORTED")
    available = memory.get("MemAvailable")
    if available is None and "MemFree" in memory:
        available = max(0, memory["MemFree"] + memory.get("Buffers", 0) + memory.get("Cached", 0)
                        + memory.get("SReclaimable", 0) - memory.get("Shmem", 0))
    ram = usage(memory.get("MemTotal"), available)
    swap = usage(memory.get("SwapTotal"), memory.get("SwapFree"))
    return SystemSnapshot(
        system, kernel, uptime, load, cpu, ram, swap, tuple(disks),
        tuple(ProcessUsage(pid, name, command, cpu_value, memory_value, tuple(sorted(ports.get(pid, ()))), start_time)
              for pid, name, command, cpu_value, memory_value, start_time in processes),
    )


def usage(total: int | None, available: int | None) -> tuple[int, int] | None:
    if total == 0:
        return 0, 0
    if total is None or available is None:
        return None
    return max(0, total - min(total, available)), total


def process_name(name: str, command: str) -> str:
    for pattern, basename in (
        (r'-Dspring\.application\.name=(?:"([^"]+)"|\x27([^\x27]+)\x27|(\S+))', False),
        (r'(?:^|\s)-jar\s+(?:"([^"]+)"|\x27([^\x27]+)\x27|(\S+))', True),
    ):
        match = re.search(pattern, command)
        if match:
            value = next(value for value in match.groups() if value)
            return posixpath.basename(value.rstrip("/")) if basename else value
    if "org.apache.catalina.startup.Bootstrap" in command:
        match = re.search(r'-Dcatalina\.base=(?:"([^"]+)"|\x27([^\x27]+)\x27|(\S+))', command)
        if match:
            value = next(value for value in match.groups() if value)
            return "Tomcat · " + posixpath.basename(value.rstrip("/"))
        return "Tomcat"
    if name.startswith("python") or name in {"node", "nodejs"}:
        extension = "py" if name.startswith("python") else "js"
        match = re.search(r"(?:^|\s)([^\s]+\." + extension + r")(?:\s|$)", command)
        if match:
            return posixpath.basename(match[1])
    return name


def format_kib(value: int) -> str:
    size = float(max(0, value))
    for unit in ("KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f}{unit}" if unit == "KB" else f"{size:.1f}{unit}"
        size /= 1024
