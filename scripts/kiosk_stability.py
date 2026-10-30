"""Reject a kiosk restart loop even while systemd briefly reports active."""

import subprocess
import sys
import time


def read_snapshot():
    result = subprocess.check_output(
        [
            "systemctl",
            "show",
            "--no-pager",
            "lyceumtv-kiosk.service",
            "-p",
            "ActiveState",
            "-p",
            "SubState",
            "-p",
            "MainPID",
            "-p",
            "NRestarts",
        ],
        text=True,
        timeout=5,
    )
    return dict(line.split("=", 1) for line in result.splitlines() if "=" in line)


def require_running(snapshot):
    if (
        snapshot.get("ActiveState") != "active"
        or snapshot.get("SubState") != "running"
        or not str(snapshot.get("MainPID", "")).isdigit()
        or int(snapshot.get("MainPID", "0")) <= 0
    ):
        raise RuntimeError("Kiosk is not running: " + str(snapshot))


def wait_for_stable(seconds=20, read=read_snapshot, sleep=time.sleep):
    baseline = read()
    require_running(baseline)
    for _ in range(seconds):
        sleep(1)
        current = read()
        require_running(current)
        if any(
            current.get(key) != baseline.get(key) for key in ("MainPID", "NRestarts")
        ):
            raise RuntimeError("Kiosk restarted during verification: " + str(current))


def main():
    try:
        wait_for_stable()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print("Kiosk process remained stable for 20 seconds; check the TV picture.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
