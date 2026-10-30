from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable

from schedule_engine import CLASS_ORDER, holiday_label
from academic_cycle import academic_week_position


def _clean_order(value: Any) -> list[str]:
    """Return a stable rotation containing every supported class exactly once."""
    raw = value if isinstance(value, list) else []
    out: list[str] = []
    for item in raw:
        name = str(item or "").strip().upper()
        if name in CLASS_ORDER and name not in out:
            out.append(name)
    for name in CLASS_ORDER:
        if name not in out:
            out.append(name)
    return out


def duty_for_date(
    day: date,
    config: dict[str, Any],
    holiday_checker: Callable[[date], str] | None = None,
) -> dict[str, Any]:
    """Resolve the duty class for an academic week.

    Rotation advances once per non-holiday school week. A full holiday week
    (Mon-Sat all marked off) does not consume a class. A manual class override
    can be selected from Operations and remains active until reset to AUTO.
    """
    checker = holiday_checker or holiday_label
    enabled = bool(config.get("duty_class_enabled", True))
    order = _clean_order(config.get("duty_rotation_order"))

    try:
        anchor = date.fromisoformat(
            str(config.get("duty_rotation_start_date") or "2026-09-01")
        )
    except Exception:
        anchor = date(2026, 9, 1)
    start_class = (
        str(config.get("duty_rotation_start_class") or order[0]).strip().upper()
    )
    if start_class not in order:
        start_class = order[0]
    start_index = order.index(start_class)

    manual = str(config.get("duty_manual_class") or "").strip().upper()
    if manual not in order:
        manual = ""

    skip_holidays = bool(config.get("duty_skip_full_holiday_weeks", True))
    label = (
        str(config.get("duty_class_label") or "ЧЕРГОВИЙ КЛАС").strip()[:40]
        or "ЧЕРГОВИЙ КЛАС"
    )

    base = {
        "enabled": enabled,
        "label": label,
        "class": "",
        "next_class": start_class,
        "mode": "manual" if manual else "auto",
        "manual_class": manual,
        "order": order,
        "start_date": anchor.isoformat(),
        "week_start": "",
        "week_end": "",
        "paused": False,
        "reason": "",
        "academic_week_number": 0,
    }

    if not enabled:
        base["reason"] = "disabled"
        return base

    pos = academic_week_position(
        day,
        anchor.isoformat(),
        checker,
        skip_full_holiday_weeks=skip_holidays,
    )
    monday = date.fromisoformat(str(pos["monday"]))
    base["week_start"] = monday.isoformat()
    base["week_end"] = (monday + timedelta(days=6)).isoformat()
    base["academic_week_number"] = int(pos["academic_week_number"])

    if bool(pos["before_start"]):
        base["reason"] = "before_start"
        return base

    active_index = int(pos["academic_week_index"])

    if bool(pos["paused"]):
        base["paused"] = True
        base["reason"] = "holiday_week"
        if manual:
            base["next_class"] = manual
        else:
            next_index = (start_index + active_index) % len(order)
            base["next_class"] = order[next_index]
        return base

    auto_class = order[(start_index + active_index) % len(order)]
    current = manual or auto_class
    current_index = order.index(current)

    base.update(
        {
            "class": current,
            "next_class": order[(current_index + 1) % len(order)],
            "reason": "manual" if manual else "rotation",
            "academic_week_number": int(pos["academic_week_number"]),
        }
    )
    return base
