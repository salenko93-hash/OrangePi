from __future__ import annotations
import json
import gzip
import hashlib
import os
import shutil
import tarfile
import tempfile
import uuid
from storage_lock import storage_lock
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
BACKUP_DIR = DATA / "backups"
INCLUDE = [
    "data/config.json",
    "data/runtime.json",
    "data/control.json",
    "data/calendar_override.json",
    "data/bells_override.json",
    "data/screens.json",
    "data/smart_ops.json",
    "data/imports/history",
    "data/current",
    "data/default",
    "public/media",
]


def list_backups() -> list[dict[str, Any]]:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    candidates = set(BACKUP_DIR.glob("lyceumtv-backup-*.tar.gz")) | set(
        BACKUP_DIR.glob("daily-*.tar.gz")
    )
    for p in candidates:
        if p.is_symlink() or not p.is_file():
            continue
        try:
            st = p.stat()
            out.append(
                {
                    "name": p.name,
                    "size": st.st_size,
                    "mtime": int(st.st_mtime),
                    "mtime_ns": st.st_mtime_ns,
                }
            )
        except OSError:
            pass
    return sorted(out, key=lambda item: (item["mtime_ns"], item["name"]), reverse=True)


def create_backup(label: str = "", keep_count: int = 14) -> dict[str, Any]:
    from media_library import MEDIA_LOCK

    with MEDIA_LOCK, storage_lock(DATA, "media"), storage_lock(DATA, "backup"):
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        safe_label = "".join(c for c in str(label or "") if c.isalnum() or c in "-_")[
            :32
        ]
        suffix = f"-{safe_label}" if safe_label else ""
        path = (
            BACKUP_DIR
            / f"lyceumtv-backup-{stamp}-{uuid.uuid4().hex[:8]}{suffix}.tar.gz"
        )
        stage = path.with_name(path.name + ".part")
        try:
            descriptor = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                with tarfile.open(fileobj=output, mode="w:gz", dereference=True) as tf:
                    for rel in INCLUDE:
                        source = ROOT / rel
                        if source.exists():
                            tf.add(source, arcname=rel, recursive=True)
                    raw = json.dumps(
                        {
                            "created_at": datetime.now().isoformat(timespec="seconds"),
                            "version": _version(),
                        },
                        ensure_ascii=False,
                    ).encode()
                    info = tarfile.TarInfo("backup_meta.json")
                    info.size = len(raw)
                    info.mtime = int(datetime.now().timestamp())
                    import io

                    tf.addfile(info, io.BytesIO(raw))
                output.flush()
                os.fsync(output.fileno())
            os.replace(stage, path)
        finally:
            stage.unlink(missing_ok=True)
        keep_count = max(1, min(100, int(keep_count)))
        for old in list_backups()[keep_count:]:
            (BACKUP_DIR / old["name"]).unlink(missing_ok=True)
        stat = path.stat()
        return {"name": path.name, "size": stat.st_size, "mtime": int(stat.st_mtime)}


def _version() -> str:
    try:
        return str(
            json.loads((DATA / "config.example.json").read_text(encoding="utf-8")).get(
                "version", ""
            )
        )
    except Exception:
        return ""


def _safe_member(name: str) -> bool:
    p = Path(name)
    return not p.is_absolute() and ".." not in p.parts


def _restore_backup(name: str) -> dict[str, Any]:
    name = Path(str(name or "")).name
    path = BACKUP_DIR / name
    if not path.is_file():
        raise FileNotFoundError("Backup не знайдено")
    with tempfile.TemporaryDirectory(prefix="lyceumtv-restore-") as tmp:
        tmp_path = Path(tmp)
        with tarfile.open(path, "r:gz") as tf:
            members = tf.getmembers()
            for m in members:
                if not _safe_member(m.name) or not (m.isfile() or m.isdir()):
                    raise ValueError("Небезпечний шлях у backup")
            options = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
            tf.extractall(tmp_path, members=members, **options)
        # Prepare every replacement before touching live files. Keep originals
        # by rename until the complete restore has committed.
        token = uuid.uuid4().hex
        prepared = []
        applied = []
        success = False

        def remove(path):
            if path.is_symlink() or path.is_file():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                shutil.rmtree(path)

        try:
            for rel in INCLUDE:
                src = tmp_path / rel
                if not src.exists():
                    continue
                dst = ROOT / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                stage = dst.with_name(dst.name + ".restore-" + token)
                old = dst.with_name(dst.name + ".rollback-" + token)
                prepared.append((dst, stage, old))
                if src.is_dir():
                    shutil.copytree(src, stage)
                else:
                    shutil.copy2(src, stage)
                if rel == "data/config.json":
                    stage.chmod(0o600)
            for dst, stage, old in prepared:
                had_old = dst.exists() or dst.is_symlink()
                if had_old:
                    os.replace(dst, old)
                try:
                    os.replace(stage, dst)
                except BaseException:
                    if had_old:
                        os.replace(old, dst)
                    raise
                applied.append((dst, old, had_old))
            success = True
        except BaseException:
            for dst, old, had_old in reversed(applied):
                remove(dst)
                if had_old:
                    os.replace(old, dst)
            raise
        finally:
            for dst, stage, old in prepared:
                remove(stage)
                if success:
                    remove(old)
    return {"name": name, "message": "Backup відновлено"}


def restore_backup(name: str) -> dict[str, Any]:
    from media_library import MEDIA_LOCK

    with MEDIA_LOCK, storage_lock(DATA, "media"), storage_lock(DATA, "backup"):
        return _restore_backup(name)


def delete_backup(name: str) -> bool:
    name = Path(str(name or "")).name
    path = BACKUP_DIR / name
    if path.is_file():
        path.unlink()
        return True
    return False


def verify_backup(path):
    """Read the complete gzip stream and every regular member before trusting it."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Backup must be a regular file")
    with gzip.open(path, "rb") as stream:
        while stream.read(1024 * 1024):
            pass
    with tarfile.open(path, "r:gz") as archive:
        names = set()
        for member in archive:
            if (
                not _safe_member(member.name)
                or member.name in names
                or member.issym()
                or member.islnk()
            ):
                raise ValueError("Unsafe backup member")
            names.add(member.name)
            if member.isfile():
                with archive.extractfile(member) as stream:
                    while stream.read(1024 * 1024):
                        pass
        if not names:
            raise ValueError("Empty backup")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"sha256": digest.hexdigest(), "size": path.stat().st_size}
