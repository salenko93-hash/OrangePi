"""Reference-aware media removal; unreadable metadata stops cleanup."""

from pathlib import Path
import re
from threading import RLock
import time
from urllib.parse import unquote, urlsplit
from json_cache import load_json
from storage_lock import storage_lock

ROOT = Path(__file__).resolve().parents[1]
MEDIA_LOCK = RLock()
_PATTERN = re.compile(r'/media/([^\s"<>?&#/]+)')


def references(root=ROOT):
    used = set()

    def scan(value):
        if isinstance(value, dict):
            for child in value.values():
                scan(child)
        elif isinstance(value, list):
            for child in value:
                scan(child)
        elif isinstance(value, str):
            for match in _PATTERN.finditer(value):
                used.add(unquote(match.group(1)))

    for name in ("config.json", "smart_ops.json", "control.json"):
        path = Path(root) / "data" / name
        if path.exists():
            try:
                scan(load_json(path))
            except (OSError, ValueError) as error:
                raise ValueError(
                    "Очищення зупинено: не читаються метадані " + name
                ) from error
    return used


def remove_unreferenced_url(url, root=ROOT):
    path = unquote(urlsplit(str(url)).path)
    if not path.startswith("/media/"):
        return False
    name = path[len("/media/") :]
    if not name or "/" in name or "\\" in name or name in {".", ".."}:
        return False
    with MEDIA_LOCK, storage_lock(Path(root) / "data", "media"):
        directory = Path(root) / "public/media"
        target = directory / name
        if name in references(root) or target.is_symlink() or not target.is_file():
            return False
        target.unlink()
        return True


def cleanup(root=ROOT, *, dry_run=True, minimum_age=3600):
    with MEDIA_LOCK, storage_lock(Path(root) / "data", "media"):
        used = references(root)
        directory = Path(root) / "public/media"
        candidates = []
        now = time.time()
        for path in directory.iterdir() if directory.exists() else []:
            if (
                path.is_symlink()
                or not path.is_file()
                or path.name.endswith(".part")
                or path.name in used
            ):
                continue
            stat = path.stat()
            if now - stat.st_mtime < minimum_age:
                continue  # A recent upload may not yet have its metadata POST.
            candidates.append((path, stat.st_size))
        count = total = 0
        for path, size in candidates:
            if not dry_run:
                path.unlink()
            count += 1
            total += size
        return {
            "ok": True,
            "dry_run": dry_run,
            "files": count,
            "bytes": total,
            "minimum_age_seconds": minimum_age,
        }
