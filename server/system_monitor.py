from __future__ import annotations
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _read_first(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _service(name: str) -> str:
    try:
        r = subprocess.run(
            ["systemctl", "is-active", name],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        return (r.stdout or r.stderr or "unknown").strip()
    except Exception:
        return "unknown"


def _ip_addresses() -> list[str]:
    try:
        r = subprocess.run(
            ["hostname", "-I"], capture_output=True, text=True, timeout=2, check=False
        )
        vals = [x for x in r.stdout.split() if x and ":" not in x]
        if vals:
            return vals
    except Exception:
        pass
    try:
        host = socket.gethostname()
        return sorted({x[4][0] for x in socket.getaddrinfo(host, None, socket.AF_INET)})
    except Exception:
        return []


def _memory() -> dict[str, int]:
    info = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            n = int(v.strip().split()[0]) * 1024
            info[k] = n
    except Exception:
        return {"total": 0, "available": 0, "used": 0}
    total = info.get("MemTotal", 0)
    avail = info.get("MemAvailable", 0)
    return {"total": total, "available": avail, "used": max(0, total - avail)}


def system_status() -> dict[str, Any]:
    uptime = 0.0
    try:
        uptime = float(_read_first("/proc/uptime").split()[0])
    except Exception:
        pass

    temp = None
    raw_temp = _read_first("/sys/class/thermal/thermal_zone0/temp")
    try:
        temp = round(float(raw_temp) / 1000.0, 1) if raw_temp else None
    except Exception:
        temp = None

    disk = shutil.disk_usage(ROOT)
    mem = _memory()
    try:
        load = [round(x, 2) for x in os.getloadavg()]
    except Exception:
        load = [0, 0, 0]

    return {
        "hostname": socket.gethostname(),
        "ips": _ip_addresses(),
        "uptime_seconds": int(uptime),
        "cpu_temp_c": temp,
        "load": load,
        "memory": mem,
        "disk": {"total": disk.total, "used": disk.used, "free": disk.free},
        "services": {
            "lyceumtv": _service("lyceumtv.service"),
            "kiosk": _service("lyceumtv-kiosk.service"),
            "watchdog": _service("lyceumtv-watchdog.timer"),
        },
        "pid": os.getpid(),
        "checked_at": int(time.time()),
    }
