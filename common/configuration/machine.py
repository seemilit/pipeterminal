"""Stable OS machine identity; network adapters and host names are excluded."""

import hashlib
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from common.i18n import tr


@lru_cache(maxsize=1)
def machine_binding() -> bytes:
    if sys.platform == "win32":
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            identity = winreg.QueryValueEx(key, "MachineGuid")[0]
    elif sys.platform == "darwin":
        result = subprocess.run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                                capture_output=True, text=True, check=True, timeout=5)
        match = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', result.stdout)
        identity = match.group(1) if match else ""
    else:
        identity = ""
        for path in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")):
            try:
                identity = path.read_text(encoding="ascii").strip()
            except FileNotFoundError:
                continue
            if identity:
                break
    if not isinstance(identity, str) or not identity.strip():
        raise ValueError(tr("无法读取稳定的机器标识，配置未保存"))
    return hashlib.sha256(("PipeTerminal/machine/v1:" + identity.strip().lower()).encode()).digest()
