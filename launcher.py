"""Stable service supervisor: workers survive app restarts; interrupted jobs roll back."""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def read_state(root):
    marker = root / "data/ota_pending"
    if not marker.exists():
        return None
    state = json.loads(marker.read_text())
    job = state.get("job", "")
    if (
        state.get("schema") != 1
        or len(job) != 32
        or any(c not in "0123456789abcdef" for c in job)
    ):
        raise ValueError("Пошкоджений маркер оновлення; запуск зупинено")
    return state


def process_exists(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (ValueError, TypeError, OSError):
        return False


def active_update(root):
    state = read_state(root)
    if not state:
        return False
    if time.time() - state.get("updated_at", 0) > 120:
        return False
    launcher = root / "data/launcher.pid"
    if not launcher.exists() or not process_exists(launcher.read_text().strip()):
        return False
    proc = Path("/proc") / launcher.read_text().strip() / "cmdline"
    if proc.exists():
        command = proc.read_bytes()
        return b"launcher.py" in command and str(root).encode() in command
    return True


def run(root):
    root = root.resolve()
    (root / "data").mkdir(exist_ok=True)
    (root / "data/launcher.pid").write_text(str(os.getpid()))
    app = worker = None
    recovering = False
    restart_at = 0

    def stop_app():
        nonlocal app
        if app and app.poll() is None:
            app.terminate()
            try:
                app.wait(timeout=10)
            except subprocess.TimeoutExpired:
                app.kill()
                app.wait()
        app = None
        (root / "data/app.pid").unlink(missing_ok=True)

    def shutdown(*_):
        stop_app()
        if worker and worker.poll() is None:
            worker.terminate()
            worker.wait(timeout=10)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    retry_at = 0
    while True:
        state = read_state(root)
        if worker and worker.poll() is not None:
            failed = worker.returncode != 0
            worker = None
            recovering = False
            if state and state["phase"] != "recovery_required":
                retry_at = time.time() + 5 if failed else 0
        if state and state["phase"] in {
            "prepared",
            "applying",
            "rolling_back",
            "recovery_required",
        }:
            if time.time() < state.get("not_before", 0):
                time.sleep(0.2)
                continue
            stop_app()
            if worker is None and time.time() >= retry_at:
                path = root / "data/update_jobs" / state["job"] / "worker.py"
                args = [sys.executable, "-B", str(path), "--root", str(root)]
                if state["phase"] != "prepared":
                    args.append("--recover")
                worker = subprocess.Popen(args, cwd=root)
                retry_at = time.time() + 15
            time.sleep(0.2)
            continue
        if state and state["phase"] == "awaiting_health" and worker is None:
            # The worker died before confirming this release. Never accept by HTTP alone.
            stop_app()
            path = root / "data/update_jobs" / state["job"] / "worker.py"
            worker = subprocess.Popen(
                [sys.executable, "-B", str(path), "--root", str(root), "--recover"],
                cwd=root,
            )
            recovering = True
            time.sleep(0.2)
            continue
        if recovering:
            time.sleep(0.2)
            continue
        if app is not None and app.poll() is not None:
            app = None
            (root / "data/app.pid").unlink(missing_ok=True)
            restart_at = time.time() + 3
        if app is None and time.time() >= restart_at:
            app = subprocess.Popen(
                [sys.executable, "-B", str(root / "server/app.py")], cwd=root
            )
            (root / "data/app.pid").write_text(str(app.pid))
        time.sleep(0.25)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--update-active", action="store_true")
    args = parser.parse_args()
    if args.update_active:
        try:
            active = active_update(args.root)
        except (OSError, ValueError):
            active = False
        raise SystemExit(0 if active else 1)
    run(args.root)
