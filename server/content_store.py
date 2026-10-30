from __future__ import annotations
from json_cache import load_json
import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CONTROL_PATH = DATA / "control.json"
_LOCK = threading.RLock()

DEFAULT = {"announcements": [], "events": [], "substitutions": []}
KINDS = {
    "announcement": "announcements",
    "event": "events",
    "substitution": "substitutions",
}


def _atomic_write(payload: dict[str, Any]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = CONTROL_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, CONTROL_PATH)


def load_control() -> dict[str, Any]:
    with _LOCK:
        if not CONTROL_PATH.exists():
            _atomic_write(DEFAULT.copy())
        try:
            obj = load_json(CONTROL_PATH)
        except Exception:
            obj = {}
        out = {
            k: list(obj.get(k, [])) if isinstance(obj.get(k, []), list) else []
            for k in DEFAULT
        }
        return out


def save_control(payload: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        clean = {}
        for k in DEFAULT:
            v = payload.get(k, [])
            clean[k] = v if isinstance(v, list) else []
        _atomic_write(clean)
        return clean


def _clean_text(value: Any, max_len: int = 500) -> str:
    return " ".join(str(value or "").replace("\x00", "").split())[:max_len]


def _bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off", ""}


_PRIORITY_LABELS = {
    "LOW": 3,
    "NORMAL": 5,
    "MEDIUM": 5,
    "HIGH": 8,
    "URGENT": 9,
    "CRITICAL": 9,
}


def _priority(value: Any, default: int = 5) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, str):
        text = value.strip().upper()
        if text in _PRIORITY_LABELS:
            return _PRIORITY_LABELS[text]
        value = text
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(0, min(9, number))


def _normalize_entries(entries: Any) -> list[dict[str, str]]:
    out = []
    if not isinstance(entries, list):
        return out
    for raw in entries[:2]:
        if not isinstance(raw, dict):
            continue
        subgroup = _clean_text(raw.get("subgroup"), 20).upper()
        if subgroup:
            digits = "".join(ch for ch in subgroup if ch.isdigit())
            subgroup = f"ГР. {digits}" if digits else subgroup
        item = {
            "subgroup": subgroup,
            "subject": _clean_text(raw.get("subject"), 120),
            "room": _clean_text(raw.get("room"), 40),
            "teacher": _clean_text(raw.get("teacher"), 120),
        }
        if any(item.values()):
            out.append(item)
    return out


def normalize(kind: str, item: dict[str, Any]) -> dict[str, Any]:
    kind = str(kind or "").strip().lower()
    if kind not in KINDS:
        raise ValueError("Невідомий тип запису")
    now = datetime.now().isoformat(timespec="seconds")
    base = {
        "id": _clean_text(item.get("id"), 80) or uuid.uuid4().hex[:12],
        "active": _bool(item.get("active"), True),
        "updated_at": now,
    }
    if kind == "announcement":
        base.update(
            {
                "title": _clean_text(item.get("title"), 120),
                "message": _clean_text(item.get("message"), 500),
                "valid_from": _clean_text(item.get("valid_from"), 20),
                "valid_to": _clean_text(item.get("valid_to"), 20),
                "priority": _priority(item.get("priority", 5), 5),
            }
        )
        if not (base["title"] or base["message"]):
            raise ValueError("Вкажіть текст оголошення")
    elif kind == "event":
        base.update(
            {
                "title": _clean_text(item.get("title"), 120),
                "message": _clean_text(item.get("message"), 500),
                "date": _clean_text(item.get("date"), 20),
                "start_time": _clean_text(item.get("start_time"), 10),
                "end_time": _clean_text(item.get("end_time"), 10),
                "priority": _priority(item.get("priority", 5), 5),
            }
        )
        if not base["title"]:
            raise ValueError("Вкажіть назву події")
    else:
        class_name = _clean_text(item.get("class"), 20)
        if class_name not in {
            "10-А",
            "10-Б",
            "10-В",
            "10-Г",
            "11-А",
            "11-Б",
            "11-В",
            "11-Г",
        }:
            raise ValueError("Невірний клас")
        try:
            lesson = int(item.get("lesson"))
        except Exception:
            raise ValueError("Невірний номер уроку")
        if lesson < 1 or lesson > 12:
            raise ValueError("Номер уроку поза діапазоном")
        scope = _clean_text(item.get("scope"), 20).lower() or "both"
        if scope not in {"both", "normal", "shelter"}:
            scope = "both"
        entries = _normalize_entries(item.get("entries"))
        if not entries:
            raise ValueError("Додайте хоча б один предмет заміни")
        base.update(
            {
                "date": _clean_text(item.get("date"), 20),
                "day": _clean_text(item.get("day"), 20).upper(),
                "week": _clean_text(item.get("week"), 20).upper() or "ALL",
                "class": class_name,
                "lesson": lesson,
                "scope": scope,
                "entries": entries,
                "note": _clean_text(item.get("note"), 200),
            }
        )
    return base


def upsert(kind: str, item: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize(kind, item)
    key = KINDS[kind]
    with _LOCK:
        data = load_control()
        arr = data[key]
        found = False
        for idx, old in enumerate(arr):
            if isinstance(old, dict) and str(old.get("id")) == normalized["id"]:
                arr[idx] = normalized
                found = True
                break
        if not found:
            arr.append(normalized)
        save_control(data)
    return normalized


def delete(kind: str, item_id: str) -> bool:
    kind = str(kind or "").strip().lower()
    if kind not in KINDS:
        raise ValueError("Невідомий тип запису")
    item_id = str(item_id or "").strip()
    with _LOCK:
        data = load_control()
        key = KINDS[kind]
        before = len(data[key])
        data[key] = [
            x
            for x in data[key]
            if not (isinstance(x, dict) and str(x.get("id")) == item_id)
        ]
        save_control(data)
        return len(data[key]) != before


def merge_with_remote(remote: dict[str, Any] | None) -> dict[str, Any]:
    remote = remote if isinstance(remote, dict) else {}
    local = load_control()
    # Local substitutions are intentionally first so the Control Center wins
    # over remote content for the same date/class/lesson.
    return {
        "announcements": list(local["announcements"])
        + list(remote.get("announcements", []) or []),
        "events": list(local["events"]) + list(remote.get("events", []) or []),
        "substitutions": list(local["substitutions"])
        + list(remote.get("substitutions", []) or []),
    }
