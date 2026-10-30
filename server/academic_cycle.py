from __future__ import annotations

from datetime import date, timedelta
from typing import Callable


HolidayChecker = Callable[[date], str]


def week_monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def full_non_school_week(monday: date, holiday_checker: HolidayChecker) -> bool:
    """Return True when every potential school day Monday-Saturday is off.

    LyceumTV can have Saturday lessons, so Sunday alone never decides whether
    an academic week is consumed. A full vacation week pauses the cycle.
    """
    return all(bool(holiday_checker(monday + timedelta(days=i))) for i in range(6))


def academic_week_position(
    day: date,
    start_date: str,
    holiday_checker: HolidayChecker,
    *,
    skip_full_holiday_weeks: bool = True,
) -> dict[str, int | str | bool]:
    """Resolve a zero-based academic week index.

    Calendar weeks that are full Mon-Sat vacations do not consume an academic
    week. The returned ``academic_week_index`` is therefore shared safely by
    numerator/denominator parity and duty-class rotation.

    During a paused vacation week, ``academic_week_index`` is the index that
    the *next* real academic week will receive.
    """
    try:
        anchor = date.fromisoformat(str(start_date or "2026-09-01"))
    except Exception:
        anchor = date(2026, 9, 1)

    anchor_monday = week_monday(anchor)
    target_monday = week_monday(day)
    calendar_offset = (target_monday - anchor_monday).days // 7

    if target_monday < anchor_monday:
        return {
            "before_start": True,
            "paused": False,
            "monday": target_monday.isoformat(),
            "calendar_week_offset": calendar_offset,
            "academic_week_index": calendar_offset,
            "academic_week_number": 0,
            "completed_academic_weeks": 0,
        }

    completed = 0
    target_paused = False
    cursor = anchor_monday
    while cursor <= target_monday:
        paused = bool(
            skip_full_holiday_weeks and full_non_school_week(cursor, holiday_checker)
        )
        if cursor == target_monday:
            target_paused = paused
        if not paused:
            completed += 1
        cursor += timedelta(days=7)

    if target_paused:
        # The vacation does not consume an index. This is exactly the index
        # assigned to the first academic week after the vacation.
        academic_index = completed
        academic_number = completed
    else:
        academic_index = max(0, completed - 1)
        academic_number = academic_index + 1

    return {
        "before_start": False,
        "paused": target_paused,
        "monday": target_monday.isoformat(),
        "calendar_week_offset": calendar_offset,
        "academic_week_index": academic_index,
        "academic_week_number": academic_number,
        "completed_academic_weeks": completed,
    }
