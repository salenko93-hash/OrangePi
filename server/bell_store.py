from __future__ import annotations
from json_cache import load_json
import json
import os
import threading
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PATH = DATA / "bells_override.json"
_LOCK = threading.RLock()


def _valid_hhmm(value: str) -> bool:
    try:
        hh, mm = [int(x) for x in str(value).split(":", 1)]
        return 0 <= hh <= 23 and 0 <= mm <= 59
    except Exception:
        return False


def load_bells() -> list[dict[str, Any]]:
    with _LOCK:
        if PATH.is_file():
            try:
                obj = load_json(PATH)
                if isinstance(obj, list) and obj:
                    return obj
            except Exception:
                pass
    for base in (DATA / "current", DATA / "default"):
        source = base / "schedule_numerator.json"
        if source.is_file():
            try:
                obj = load_json(source, copy=False)
                bells = obj.get("bellSchedule", [])
                if isinstance(bells, list) and bells:
                    return [dict(bell) for bell in bells]
            except Exception:
                pass
    return []


def save_bells(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        raise ValueError("Дзвінки мають бути масивом")
    clean: list[dict[str, Any]] = []
    seen = set()
    for raw in items:
        if not isinstance(raw, dict):
            continue
        try:
            lesson = int(raw.get("lesson"))
        except Exception:
            raise ValueError("Невірний номер уроку")
        start, end = str(raw.get("start", "")).strip(), str(raw.get("end", "")).strip()
        if lesson < 1 or lesson > 12 or lesson in seen:
            raise ValueError("Невірний або повторний номер уроку")
        if not _valid_hhmm(start) or not _valid_hhmm(end):
            raise ValueError("Час має формат HH:MM")
        seen.add(lesson)
        clean.append({"lesson": lesson, "start": start, "end": end})
    clean.sort(key=lambda x: x["lesson"])
    if not clean:
        raise ValueError("Розклад дзвінків порожній")
    with _LOCK:
        DATA.mkdir(parents=True, exist_ok=True)
        tmp = PATH.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, PATH)
    return clean
