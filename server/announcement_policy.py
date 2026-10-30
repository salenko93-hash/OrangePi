"""Pure time window decisions; all instants in site-local timezone."""

from datetime import datetime, time


def after_school_info(now: datetime, phase: str, mode: str = "NORMAL") -> bool:
    return mode == "NORMAL" and phase == "AFTER_SCHOOL" and now.time() < time(17, 0)


def event_display(item: dict, now: datetime, include_upcoming: bool = False) -> bool:
    if not item.get("active", True):
        return False
    event_date = str(item.get("date", "")).strip()
    if not event_date or event_date != now.date().isoformat():
        return False
    start = str(item.get("start_time", "")).strip()
    end = str(item.get("end_time", "")).strip()
    clock = now.strftime("%H:%M")
    # Past events cannot be presented as upcoming or in progress.
    if end and clock > end:
        return False
    if start and clock < start and not include_upcoming:
        return False
    return True


def progress_percent(remaining: int, duration: int) -> float:
    if duration <= 0:
        return 0.0
    return max(0.0, min(100.0, (1 - remaining / duration) * 100))
