"""Recoverable code updates. The supervisor stops the app before any replacement.

An immutable copy of this stdlib-only worker lives in every job. Live data and
media are never part of the code transaction. The bootstrap remains installer-owned.
"""

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import urllib.request
import uuid

DIRECTORIES = ("server", "public", "scripts", "data/default")
TOP = ("README.md", "requirements.txt", "data/config.example.json")
REQUIRED = (
    "server/app.py",
    "server/update_transaction.py",
    "server/version.py",
    "public/index.html",
    "public/js/app.js",
    "data/config.example.json",
    "launcher.py",
)
PHASES_BLOCKING = {"prepared", "applying", "rolling_back", "recovery_required"}


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        descriptor = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as out:
            json.dump(value, out, ensure_ascii=False)
            out.flush()
            os.fsync(out.fileno())
        os.replace(stage, path)
        if os.name == "posix":
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        stage.unlink(missing_ok=True)


def read_state(root):
    path = Path(root) / "data/ota_pending"
    if not path.exists():
        return None
    value = json.loads(path.read_text())
    if (
        not isinstance(value, dict)
        or value.get("schema") != 1
        or not valid_job(value.get("job"))
    ):
        raise ValueError("Невідомий стан OTA; потрібне відновлення перед запуском")
    return value


def valid_job(value):
    return (
        isinstance(value, str)
        and len(value) == 32
        and all(c in "0123456789abcdef" for c in value)
    )


def job_path(root, job):
    if not valid_job(job):
        raise ValueError("Invalid update job")
    return Path(root) / "data/update_jobs" / job


def set_phase(root, state, phase, **extra):
    state = {**state, **extra, "phase": phase, "updated_at": time.time()}
    atomic_json(Path(root) / "data/ota_pending", state)
    return state


def inventory(root):
    root = Path(root)
    files = set()
    for directory in DIRECTORIES:
        files.update(
            p.relative_to(root).as_posix()
            for p in (root / directory).rglob("*")
            if p.is_file() and not p.is_symlink()
        )
    files.update(name for name in TOP if (root / name).is_file())
    return sorted(
        name
        for name in files
        if not name.startswith("public/media/")
        and "__pycache__" not in Path(name).parts
        and not name.endswith((".pyc", ".pyo"))
    )


def version_at(root):
    value = json.loads(
        (Path(root) / "data/config.example.json").read_text(encoding="utf-8-sig")
    )
    return str(value["version"])


def validate_release(source):
    source = Path(source)
    for name in REQUIRED:
        if not (source / name).is_file():
            raise ValueError("Incomplete release: " + name)
    manifest_path = source / "PACKAGE_SHA256.json"
    if not manifest_path.is_file():
        raise ValueError("Release file manifest is missing")
    manifest = json.loads(manifest_path.read_text())
    if not isinstance(manifest, dict):
        raise ValueError("Invalid release manifest")
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        name = path.relative_to(source).as_posix()
        if name == "PACKAGE_SHA256.json":
            continue
        if manifest.get(name) != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError("Release hash mismatch: " + name)
    for name in manifest:
        if (
            Path(name).is_absolute()
            or ".." in Path(name).parts
            or not (source / name).is_file()
        ):
            raise ValueError("Invalid release manifest path")
    for path in list((source / "server").glob("*.py")) + [source / "launcher.py"]:
        ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    assignment = ast.parse((source / "server/version.py").read_text()).body
    version = next(
        (
            ast.literal_eval(node.value)
            for node in assignment
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "VERSION"
                for target in node.targets
            )
        ),
        None,
    )
    if version != version_at(source):
        raise ValueError("Release version mismatch")
    return version


def copy_file(source, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = destination.with_name(destination.name + ".update-tmp")
    try:
        shutil.copy2(source, stage)
        if destination.suffix == ".sh":
            stage.chmod(0o755)
        with stage.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(stage, destination)
    finally:
        stage.unlink(missing_ok=True)


def save_snapshot(root, job):
    root = Path(root)
    job = Path(job)
    names = inventory(root)
    hashes = {}
    for name in names:
        copy_file(root / name, job / "old" / name)
        hashes[name] = hashlib.sha256((job / "old" / name).read_bytes()).hexdigest()
    atomic_json(job / "old-files.json", hashes)
    return names


def prepare(root, source):
    from storage_lock import storage_lock

    root = Path(root)
    source = Path(source)
    with storage_lock(root / "data", "update-prepare"):
        if (root / "data/ota_pending").exists():
            raise ValueError("Оновлення або відновлення вже виконується")
        target = validate_release(source)
        files = inventory(source)
        size = sum((source / name).stat().st_size for name in files)
        if shutil.disk_usage(root).free < size * 3 + 16 * 1024 * 1024:
            raise ValueError("Недостатньо місця для оновлення та відкату")
        job_id = uuid.uuid4().hex
        job = job_path(root, job_id)
        job.mkdir(parents=True)
        try:
            for name in files:
                copy_file(source / name, job / "new" / name)
            save_snapshot(root, job)
            shutil.copy2(__file__, job / "worker.py")
            info = {
                "schema": 1,
                "job": job_id,
                "target": target,
                "previous": version_at(root),
                "new_files": files,
                "phase": "prepared",
                "action": "apply",
                "not_before": time.time() + 2,
                "updated_at": time.time(),
            }
            atomic_json(job / "job.json", info)
            atomic_json(root / "data/ota_pending", info)
        except BaseException:
            shutil.rmtree(job, ignore_errors=True)
            raise
        return {
            "ok": True,
            "queued": True,
            "job": job_id,
            "target": target,
            "message": "Оновлення підготовлено; перевірка нової версії виконується після перезапуску",
        }


def restore_files(root, job, new_files):
    root = Path(root)
    job = Path(job)
    old = json.loads((job / "old-files.json").read_text())
    for name, digest in old.items():
        if hashlib.sha256((job / "old" / name).read_bytes()).hexdigest() != digest:
            raise ValueError("Snapshot hash mismatch: " + name)
    for name in set(new_files) - set(old):
        (root / name).unlink(missing_ok=True)
    for name in old:
        copy_file(job / "old" / name, root / name)


def complete(root, state, phase, **extra):
    root = Path(root)
    state = {
        **state,
        **extra,
        "phase": phase,
        "finished_at": time.time(),
        "updated_at": time.time(),
    }
    atomic_json(job_path(root, state["job"]) / "result.json", state)
    atomic_json(root / "data/last_update.json", state)
    (root / "data/ota_pending").unlink(missing_ok=True)
    prune_jobs(root)


def prune_jobs(root):
    root = Path(root)
    # Keep three completed recovery snapshots, never an in-flight job.
    jobs = sorted(
        (root / "data/update_jobs").iterdir(),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    completed = [path for path in jobs if (path / "result.json").is_file()]
    for path in completed[3:]:
        shutil.rmtree(path)


def health_ok(root, expected):
    cfg = json.loads((Path(root) / "data/config.json").read_text())
    port = int(cfg.get("port", 8080))
    if not 1 <= port <= 65535:
        return False
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/health", timeout=2
        ) as response:
            value = json.load(response)
            return (
                response.status == 200
                and value.get("ok") is True
                and value.get("service") == "LyceumTV"
                and value.get("version") == expected
            )
    except (OSError, ValueError):
        return False


def wait_app_stopped(root, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        path = Path(root) / "data/app.pid"
        if not path.exists():
            return
        try:
            pid = int(path.read_text())
            os.kill(pid, 0)
        except (ValueError, ProcessLookupError, FileNotFoundError):
            return
        time.sleep(0.1)
    raise TimeoutError("Supervisor did not stop the app before code replacement")


def rollback(root, state, reason):
    state = set_phase(root, state, "rolling_back", error=str(reason))
    wait_app_stopped(root)
    restore_files(root, job_path(root, state["job"]), state.get("new_files", []))
    complete(root, state, "rolled_back", error=str(reason))


def execute(root, *, recover=False, check=None, timeout=60, poll=1):
    root = Path(root)
    state = read_state(root)
    if not state:
        return
    state = set_phase(root, state, state["phase"], worker_pid=os.getpid())
    job = job_path(root, state["job"])
    try:
        if recover or state.get("action") == "rollback":
            rollback(root, state, "Відновлення попередньої версії")
            return
        wait_app_stopped(root)
        state = set_phase(root, state, "applying")
        old = json.loads((job / "old-files.json").read_text())
        for name in state["new_files"]:
            copy_file(job / "new" / name, root / name)
        for name in set(old) - set(state["new_files"]):
            (root / name).unlink(missing_ok=True)
        state = set_phase(root, state, "awaiting_health")
        check = check or (lambda expected: health_ok(root, expected))
        deadline = time.monotonic() + timeout
        consecutive = 0
        while time.monotonic() < deadline:
            consecutive = consecutive + 1 if check(state["target"]) else 0
            if consecutive >= 3:
                complete(root, state, "healthy")
                return
            time.sleep(poll)
        raise TimeoutError("Нова версія не пройшла три послідовні health-перевірки")
    except Exception as error:
        try:
            rollback(root, state, error)
        except Exception as recovery_error:
            set_phase(root, state, "recovery_required", error=str(recovery_error))
            raise


def snapshot(root):
    from storage_lock import storage_lock

    root = Path(root)
    with storage_lock(root / "data", "update-prepare"):
        if read_state(root):
            raise ValueError("Оновлення вже виконується")
        job_id = uuid.uuid4().hex
        job = job_path(root, job_id)
        job.mkdir(parents=True)
        try:
            names = save_snapshot(root, job)
            shutil.copy2(__file__, job / "worker.py")
            info = {
                "schema": 1,
                "job": job_id,
                "target": version_at(root),
                "previous": version_at(root),
                "new_files": names,
                "action": "rollback",
                "phase": "snapshot",
                "updated_at": time.time(),
            }
            atomic_json(job / "job.json", info)
            atomic_json(job / "result.json", info)
            prune_jobs(root)
            return job_id
        except BaseException:
            shutil.rmtree(job, ignore_errors=True)
            raise


def queue_rollback(root):
    root = Path(root)
    if read_state(root):
        raise ValueError("Інше оновлення вже виконується")
    candidates = sorted(
        (root / "data/update_jobs").glob("*/old-files.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise ValueError("Немає знімка попередньої версії")
    info = json.loads((candidates[0].parent / "job.json").read_text())
    info.update(
        action="rollback",
        phase="prepared",
        not_before=time.time() + 2,
        updated_at=time.time(),
    )
    atomic_json(root / "data/ota_pending", info)
    return info["job"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--recover", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--snapshot", action="store_true")
    args = parser.parse_args()
    if args.snapshot:
        print(snapshot(args.root))
    elif args.rollback:
        print(queue_rollback(args.root))
    else:
        pending = read_state(args.root)
        timeout = float(pending.get("health_timeout_seconds", 60)) if pending else 60
        execute(args.root, recover=args.recover, timeout=max(3, min(180, timeout)))
