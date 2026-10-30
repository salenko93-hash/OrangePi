from __future__ import annotations
from json_cache import load_json
import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PATH = DATA / "calendar_override.json"
_LOCK = threading.RLock()
DEFAULT = {"daysOff": [], "ranges": [], "openEndedRanges": []}


def _atomic_write(payload: dict[str, Any]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, PATH)


def load_override() -> dict[str, Any]:
    with _LOCK:
        if not PATH.exists():
            _atomic_write(DEFAULT.copy())
        try:
            obj = load_json(PATH)
        except Exception:
            obj = {}
        return {
            k: list(obj.get(k, [])) if isinstance(obj.get(k, []), list) else []
            for k in DEFAULT
        }


def save_override(payload: dict[str, Any]) -> dict[str, Any]:
    clean = {
        k: list(payload.get(k, [])) if isinstance(payload.get(k, []), list) else []
        for k in DEFAULT
    }
    with _LOCK:
        _atomic_write(clean)
    return clean


def _text(v: Any, n: int = 120) -> str:
    return " ".join(str(v or "").split())[:n]


def upsert(kind: str, item: dict[str, Any]) -> dict[str, Any]:
    if kind not in DEFAULT:
        raise ValueError("Невідомий тип календаря")
    base = {
        "id": _text(item.get("id"), 80) or uuid.uuid4().hex[:12],
        "label": _text(item.get("label"), 120),
    }
    if kind == "daysOff":
        base["date"] = _text(item.get("date"), 20)
        if not base["date"]:
            raise ValueError("Вкажіть дату")
    elif kind == "ranges":
        base["from"] = _text(item.get("from"), 20)
        base["to"] = _text(item.get("to"), 20)
        if not base["from"] or not base["to"]:
            raise ValueError("Вкажіть початок і кінець")
    else:
        base["from"] = _text(item.get("from"), 20)
        if not base["from"]:
            raise ValueError("Вкажіть початок")
    if not base["label"]:
        base["label"] = "Вихідний" if kind == "daysOff" else "Канікули"
    with _LOCK:
        data = load_override()
        arr = data[kind]
        for idx, old in enumerate(arr):
            if isinstance(old, dict) and str(old.get("id")) == base["id"]:
                arr[idx] = base
                break
        else:
            arr.append(base)
        save_override(data)
    return base


def delete(kind: str, item_id: str) -> bool:
    if kind not in DEFAULT:
        raise ValueError("Невідомий тип календаря")
    with _LOCK:
        data = load_override()
        before = len(data[kind])
        data[kind] = [
            x
            for x in data[kind]
            if not (isinstance(x, dict) and str(x.get("id")) == str(item_id))
        ]
        save_override(data)
        return len(data[kind]) != before
