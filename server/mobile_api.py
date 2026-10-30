from __future__ import annotations

from datetime import date
from typing import Any

from schedule_engine import (
    CLASS_ORDER,
    DAY_KEYS,
    DAY_UA,
    _structured_entries,
    _substitution,
    effective_bells,
    holiday_label,
    read_content,
    read_json,
    week_info,
)


_PRIORITY_LABELS = {
    "LOW": 3,
    "NORMAL": 5,
    "MEDIUM": 5,
    "HIGH": 8,
    "URGENT": 9,
    "CRITICAL": 9,
}


def _priority_int(value: Any, default: int = 5) -> int:
    """Coerce legacy/string announcement priorities without breaking Mobile API."""
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


def _active_announcements_for(day: date) -> list[dict[str, Any]]:
    content = read_content()
    out: list[dict[str, Any]] = []
    iso = day.isoformat()
    for item in content.get("announcements", []) or []:
        if not isinstance(item, dict) or item.get("active", True) is False:
            continue
        start = str(item.get("valid_from", "") or "")
        end = str(item.get("valid_to", "") or "")
        if start and iso < start:
            continue
        if end and iso > end:
            continue
        out.append(
            {
                "title": str(item.get("title", "") or ""),
                "message": str(item.get("message", "") or ""),
                "priority": _priority_int(item.get("priority", 5), 5),
            }
        )
    out.sort(key=lambda x: -x["priority"])
    return out[:8]


def build_mobile_schedule(
    class_name: str, day: date, config: dict[str, Any]
) -> dict[str, Any]:
    class_name = str(class_name or "").strip().upper()
    if class_name not in CLASS_ORDER:
        raise ValueError("Невірний клас")

    wk = week_info(day, str(config.get("numerator_start_date", "2026-09-01")))
    base = {
        "ok": True,
        "title": str(config.get("mobile_title", "Розклад ліцею") or "Розклад ліцею"),
        "class": class_name,
        "date": day.isoformat(),
        "day_label": DAY_UA[day.weekday()],
        "week": wk,
        "holiday": "",
        "lessons": [],
        "bells": [],
        "announcements": _active_announcements_for(day),
    }

    if day.weekday() not in DAY_KEYS:
        base["holiday"] = "Занять за розкладом немає"
        return base

    label = holiday_label(day)
    if label:
        base["holiday"] = label
        return base

    day_key = DAY_KEYS[day.weekday()]
    name = "schedule_" + ("numerator" if wk["numerator"] else "denominator") + ".json"
    root = read_json(name, copy=False)
    day_obj = (root.get("days") or {}).get(day_key, {})
    class_lessons = day_obj.get(class_name, {}) if isinstance(day_obj, dict) else {}
    if not isinstance(class_lessons, dict):
        class_lessons = {}

    bells = effective_bells(root)
    bell_map = {}
    for bell in bells:
        try:
            n = int(bell.get("lesson"))
        except Exception:
            continue
        bell_map[n] = {
            "lesson": n,
            "start": str(bell.get("start", "")),
            "end": str(bell.get("end", "")),
        }
    base["bells"] = [bell_map[n] for n in sorted(bell_map)]

    content = read_content()
    lesson_numbers = set()
    for key in class_lessons:
        try:
            lesson_numbers.add(int(key))
        except Exception:
            pass
    lesson_numbers.update(bell_map.keys())

    for lesson in sorted(n for n in lesson_numbers if 1 <= n <= 12):
        entries = class_lessons.get(str(lesson), [])
        replacement = _substitution(
            content, day, day_key, wk["label"], class_name, lesson, False
        )
        is_sub = replacement is not None
        if is_sub:
            entries = replacement
        structured = _structured_entries(entries)
        if not structured and lesson not in class_lessons:
            continue
        base["lessons"].append(
            {
                "lesson": lesson,
                "start": bell_map.get(lesson, {}).get("start", ""),
                "end": bell_map.get(lesson, {}).get("end", ""),
                "entries": structured,
                "substitution": is_sub,
            }
        )
    return base
