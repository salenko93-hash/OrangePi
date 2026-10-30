from __future__ import annotations
import json
import threading
from pathlib import Path
from typing import Any
from timezone_utils import local_now

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "data" / "logs"
LOG_PATH = LOG_DIR / "events.jsonl"
_LOCK = threading.RLock()
_MAX_BYTES = 2 * 1024 * 1024


def _now() -> str:
    return local_now("Europe/Kyiv").isoformat(timespec="seconds")


def _rotate() -> None:
    if not LOG_PATH.exists() or LOG_PATH.stat().st_size <= _MAX_BYTES:
        return
    old = LOG_PATH.with_suffix(".jsonl.1")
    try:
        if old.exists():
            old.unlink()
        LOG_PATH.replace(old)
    except OSError:
        pass


def write_event(
    kind: str,
    message: str,
    details: dict[str, Any] | None = None,
    actor: str = "system",
) -> None:
    item = {
        "at": _now(),
        "kind": str(kind or "event"),
        "message": str(message or ""),
        "actor": str(actor or "system"),
        "details": details or {},
    }
    with _LOCK:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        _rotate()
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")


def read_events(limit: int = 120) -> list[dict[str, Any]]:
    limit = max(1, min(1000, int(limit)))
    with _LOCK:
        if not LOG_PATH.exists():
            return []
        try:
            # Read the requested tail, not the entire (up to 2 MB) log.
            with LOG_PATH.open("rb") as stream:
                stream.seek(0, 2)
                position = stream.tell()
                chunks = []
                newlines = 0
                while position > 0 and newlines <= limit:
                    size = min(position, 8192)
                    position -= size
                    stream.seek(position)
                    chunk = stream.read(size)
                    chunks.append(chunk)
                    newlines += chunk.count(b"\n")
            lines = (
                b"".join(reversed(chunks))
                .decode("utf-8", errors="replace")
                .splitlines()
            )
        except Exception:
            return []
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                out.append(obj)
        except Exception:
            continue
    return list(reversed(out))


def clear_events() -> None:
    with _LOCK:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        LOG_PATH.write_text("", encoding="utf-8")
