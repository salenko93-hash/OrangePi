"""Administrator-triggered GitHub updates; never an automatic installer."""

import argparse
from contextlib import suppress
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import time
import uuid

import github_releases as github
import update_transaction as transaction
from backup_manager import verify_backup
from storage_lock import storage_lock

ROOT = Path(__file__).resolve().parents[1]


def record(root, action, **details):
    path = Path(root) / "data/logs/github-updates.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Logs contain release/job identifiers, never config values or HTTP headers.
    if path.is_symlink():
        raise ValueError("Update log must not be a symlink")
    if path.exists() and path.stat().st_size > 2 * 1024 * 1024:
        os.replace(path, path.with_suffix(".jsonl.1"))
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as output:
        output.write(
            json.dumps({"at": time.time(), "action": action, **details}) + "\n"
        )


def check(root=ROOT, tag=None, *, allow_prerelease=False):
    info = github.release(tag, allow_prerelease=allow_prerelease)
    info["current"] = transaction.version_at(root)
    info["available"] = github.version_tuple(info["version"]) > github.version_tuple(
        info["current"]
    )
    return {"ok": True, "configured": True, **info}


def backup(root):
    """Private, verified data/media backup; transaction.prepare snapshots code."""
    root = Path(root)
    with storage_lock(root / "data", "media"), storage_lock(root / "data", "backup"):
        files = []
        for base in (root / "data", root / "public/media"):
            if not base.exists():
                continue
            if base.is_symlink():
                raise ValueError("Backup source must not be a symlink")
            for directory, subdirs, names in os.walk(base, followlinks=False):
                current = Path(directory)
                subdirs[:] = [
                    name
                    for name in subdirs
                    if current / name
                    not in {
                        root / "data/backups",
                        root / "data/update_jobs",
                        root / "data/logs",
                        root / "data/.locks",
                    }
                ]
                if any((current / name).is_symlink() for name in subdirs + names):
                    raise ValueError("Backup refuses linked local data")
                files.extend(current / name for name in names)
        size = sum(path.stat().st_size for path in files)
        if shutil.disk_usage(root).free < size + 64 * 1024 * 1024:
            raise ValueError("Insufficient space for verified pre-update backup")
        directory = root / "data/backups"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = directory / ("pre-github-" + uuid.uuid4().hex + ".tar.gz")
        stage = path.with_suffix(".part")
        try:
            descriptor = os.open(stage, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                with tarfile.open(fileobj=output, mode="w:gz") as archive:
                    for source in files:
                        archive.add(
                            source,
                            arcname=source.relative_to(root).as_posix(),
                            recursive=False,
                        )
                output.flush()
                os.fsync(output.fileno())
            with tarfile.open(stage, "r:gz") as archive:
                members = archive.getmembers()
                if {m.name for m in members} != {
                    p.relative_to(root).as_posix() for p in files
                }:
                    raise ValueError("Incomplete pre-update backup")
                for member in members:
                    if not member.isfile():
                        raise ValueError("Backup contains non-regular files")
                    with archive.extractfile(member) as stream:
                        while stream.read(1024 * 1024):
                            pass  # Read every member and validate the gzip/CRC stream.
            os.replace(stage, path)
        finally:
            stage.unlink(missing_ok=True)
        return {"name": path.name, **verify_backup(path)}


def wait_result(root, job, timeout=240):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        path = transaction.job_path(root, job) / "result.json"
        pending = transaction.read_state(root)
        if (
            pending
            and pending["job"] == job
            and pending["phase"] == "recovery_required"
        ):
            raise RuntimeError("Update requires manual recovery; snapshot retained")
        if path.exists() and pending is None:
            result = json.loads(path.read_text())
            if result.get("job") != job or result.get("phase") not in {
                "healthy",
                "rolled_back",
            }:
                raise ValueError("Unexpected transaction result")
            expected = (
                result.get("previous", result["target"])
                if result["phase"] == "rolled_back"
                else result["target"]
            )
            if transaction.health_ok(root, expected):
                return result
        time.sleep(0.25)
    raise TimeoutError("Transaction still pending; inspect status before retrying")


def require_supervisor(root):
    pid = root / "data/launcher.pid"
    if os.name != "posix" or not pid.exists():
        raise ValueError("Apply requires the Orange Pi POSIX supervisor")
    number = int(pid.read_text())
    if number <= 0:
        raise ValueError("Invalid supervisor PID")
    os.kill(number, 0)
    command = Path("/proc") / str(number) / "cmdline"
    if (
        not command.is_file()
        or b"launcher.py" not in command.read_bytes()
        or str(root.resolve()).encode() not in command.read_bytes()
    ):
        raise ValueError("Supervisor does not belong to this installation")


def apply(root, tag, approve, *, allow_prerelease=False, timeout=240):
    root = Path(root)
    with storage_lock(root / "data", "official-update"):
        info = check(root, tag, allow_prerelease=allow_prerelease)
        if approve != info["version"]:
            raise ValueError(
                "Administrator must explicitly approve the exact target version"
            )
        if not info["available"]:
            raise ValueError("Same or older runtime version cannot be applied")
        if transaction.read_state(root):
            raise ValueError("A transaction is already pending")
        require_supervisor(root)
        raw = github.package(info)
        with tempfile.TemporaryDirectory(prefix="orangepi-update-") as directory:
            source = github.unpack(raw, directory, info["version"])
            saved = backup(root)
            record(root, "backup.verified", **saved)
            queued = transaction.prepare(root, source)
        record(root, "update.queued", tag=tag, job=queued["job"], backup=saved["name"])
    result = wait_result(root, queued["job"], timeout)
    record(root, "update.finished", job=queued["job"], phase=result["phase"])
    if result["phase"] != "healthy":
        raise RuntimeError(
            "Health check failed; code rolled back and local data preserved"
        )
    return {"ok": True, "result": result, "backup": saved}


def rollback(root, approve, *, timeout=240):
    if approve != "rollback":
        raise ValueError("Manual rollback requires --approve rollback")
    with storage_lock(Path(root) / "data", "official-update"):
        require_supervisor(Path(root))
        if transaction.read_state(root):
            raise ValueError("Resolve the pending transaction before manual rollback")
        saved = backup(root)
        job = transaction.queue_rollback(root)
        record(root, "rollback.queued", job=job, backup=saved["name"])
    result = wait_result(root, job, timeout)
    record(root, "rollback.finished", job=job, phase=result["phase"])
    if result["phase"] != "rolled_back":
        raise RuntimeError("Rollback did not restore the snapshot")
    return {"ok": True, "result": result, "backup": saved}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "command", choices=["check", "download", "apply", "rollback", "status"]
    )
    parser.add_argument("--tag")
    parser.add_argument("--allow-prerelease", action="store_true")
    parser.add_argument("--approve", default="")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            result = check(args.root, args.tag, allow_prerelease=args.allow_prerelease)
            record(
                args.root,
                "release.checked",
                tag=result["tag"],
                available=result["available"],
            )
        elif args.command == "download":
            if args.output is None or args.output.exists():
                raise ValueError("--output must name a new directory")
            info = github.release(args.tag, allow_prerelease=args.allow_prerelease)
            raw = github.package(info)
            # Invalid archives leave no installation or partial output behind.
            with tempfile.TemporaryDirectory(prefix="orangepi-download-") as temporary:
                source = github.unpack(raw, temporary, info["version"])
                args.output.mkdir(parents=True)
                (args.output / info["name"]).write_bytes(raw)
                (args.output / (info["name"] + ".sha256")).write_text(
                    info["sha256"] + "  " + info["name"] + "\n"
                )
                shutil.copytree(source, args.output / source.name)
            result = {"ok": True, **info, "directory": str(args.output.resolve())}
        elif args.command == "apply":
            if not args.tag:
                raise ValueError("apply requires an explicit --tag")
            result = apply(
                args.root,
                args.tag,
                args.approve,
                allow_prerelease=args.allow_prerelease,
            )
        elif args.command == "rollback":
            result = rollback(args.root, args.approve)
        else:
            result = {"ok": True, "pending": transaction.read_state(args.root)}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as error:
        if args.command in {"apply", "rollback", "check"}:
            with suppress(OSError, ValueError):
                record(
                    args.root, "update.error", command=args.command, error=str(error)
                )
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
