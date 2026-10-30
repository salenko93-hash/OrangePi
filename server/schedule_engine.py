from __future__ import annotations
from json_cache import load_json
import re
from datetime import date, datetime, time as dtime
from pathlib import Path
from typing import Any

from content_store import merge_with_remote
from calendar_store import load_override as load_calendar_override
from bell_store import load_bells as load_bells_override
from timezone_utils import local_now
from academic_cycle import academic_week_position
from announcement_policy import event_display

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CURRENT = DATA / "current"
DEFAULT = DATA / "default"

CLASS_ORDER = ["10-А", "10-Б", "10-В", "10-Г", "11-А", "11-Б", "11-В", "11-Г"]
DAY_KEYS = {
    0: "MONDAY",
    1: "TUESDAY",
    2: "WEDNESDAY",
    3: "THURSDAY",
    4: "FRIDAY",
    5: "SATURDAY",
}
DAY_UA = {
    0: "ПОНЕДІЛОК",
    1: "ВІВТОРОК",
    2: "СЕРЕДА",
    3: "ЧЕТВЕР",
    4: "П’ЯТНИЦЯ",
    5: "СУБОТА",
    6: "НЕДІЛЯ",
}

GROUP_RE = re.compile(r"^(?:гр\.?|група|підгрупа)\s*([0-9]+)\s*[.:]?\s*", re.I | re.U)

_CALENDAR_CACHE_SIG: tuple[Any, ...] | None = None
_CALENDAR_CACHE_SOURCES: list[dict[str, Any]] = []
_WEEK_INFO_CACHE: dict[tuple[str, str, tuple[Any, ...]], dict[str, Any]] = {}


def read_json(name: str, *, copy: bool = True) -> dict[str, Any]:
    for base in (CURRENT, DEFAULT):
        path = base / name
        if path.is_file():
            try:
                obj = load_json(path, copy=copy)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                pass
    raise FileNotFoundError(name)


def read_content() -> dict[str, Any]:
    try:
        remote = read_json("content.json")
    except Exception:
        remote = {}
    return merge_with_remote(remote)


def effective_bells(schedule_root: dict[str, Any]) -> list[dict[str, Any]]:
    local = load_bells_override()
    if local:
        return local
    bells = schedule_root.get("bellSchedule", [])
    return bells if isinstance(bells, list) else []


def _calendar_signature() -> tuple[Any, ...]:
    paths = (
        CURRENT / "calendar.json",
        DEFAULT / "calendar.json",
        DATA / "calendar_override.json",
    )
    out: list[Any] = []
    for path in paths:
        try:
            st = path.stat()
            out.extend((str(path), st.st_mtime_ns, st.st_size))
        except OSError:
            out.extend((str(path), 0, 0))
    return tuple(out)


def _calendar_sources() -> tuple[list[dict[str, Any]], tuple[Any, ...]]:
    """Load calendar/override only when their files changed on disk."""
    global _CALENDAR_CACHE_SIG, _CALENDAR_CACHE_SOURCES, _WEEK_INFO_CACHE

    sig = _calendar_signature()
    if _CALENDAR_CACHE_SIG == sig and _CALENDAR_CACHE_SOURCES:
        return _CALENDAR_CACHE_SOURCES, sig

    try:
        cal = read_json("calendar.json")
    except Exception:
        cal = {}
    local = load_calendar_override()
    sources = [x for x in (local, cal) if isinstance(x, dict)]

    _CALENDAR_CACHE_SIG = sig
    _CALENDAR_CACHE_SOURCES = sources
    _WEEK_INFO_CACHE = {}
    return sources, sig


def _holiday_from_sources(day: date, sources: list[dict[str, Any]]) -> str:
    iso = day.isoformat()
    for source in sources:
        for item in source.get("daysOff", []) or []:
            if isinstance(item, dict) and item.get("date") == iso:
                return str(item.get("label") or "Вихідний")
        for item in source.get("ranges", []) or []:
            if not isinstance(item, dict):
                continue
            try:
                frm, to = (
                    date.fromisoformat(item["from"]),
                    date.fromisoformat(item["to"]),
                )
                if frm <= day <= to:
                    return str(item.get("label") or "Канікули")
            except Exception:
                pass
        for item in source.get("openEndedRanges", []) or []:
            if not isinstance(item, dict):
                continue
            try:
                frm = date.fromisoformat(item["from"])
                if day >= frm:
                    return str(item.get("label") or "Канікули")
            except Exception:
                pass
    return ""


def holiday_label(day: date) -> str:
    sources, _ = _calendar_sources()
    return _holiday_from_sources(day, sources)


def week_info(day: date, numerator_start_date: str) -> dict[str, Any]:
    """Resolve numerator/denominator from academic weeks, not calendar weeks.

    Full Monday-Saturday vacation weeks pause the cycle. After a vacation the
    next real academic week continues with the next numerator/denominator type.
    """
    sources, sig = _calendar_sources()
    start_date = str(numerator_start_date or "2026-09-01")
    cache_key = (day.isoformat(), start_date, sig)
    cached = _WEEK_INFO_CACHE.get(cache_key)
    if cached is not None:
        return dict(cached)

    checker = lambda d: _holiday_from_sources(d, sources)
    pos = academic_week_position(
        day,
        start_date,
        checker,
        skip_full_holiday_weeks=True,
    )

    academic_index = int(pos["academic_week_index"])
    numerator = academic_index % 2 == 0
    label = "ЧИСЕЛЬНИК" if numerator else "ЗНАМЕННИК"

    if bool(pos["paused"]):
        result = {
            # During vacation no schedule is rendered. `numerator` describes
            # the NEXT academic week after the pause for backward compatibility.
            "numerator": numerator,
            "label": "ПАУЗА",
            "next_label": label,
            "paused": True,
            "reason": "holiday_week",
            "week_offset": academic_index,
            "academic_week_index": academic_index,
            "academic_week_number": int(pos["academic_week_number"]),
            "calendar_week_offset": int(pos["calendar_week_offset"]),
            "monday": str(pos["monday"]),
        }
    else:
        result = {
            "numerator": numerator,
            "label": label,
            "next_label": "ЗНАМЕННИК" if numerator else "ЧИСЕЛЬНИК",
            "paused": False,
            "reason": "before_start" if bool(pos["before_start"]) else "academic_week",
            "week_offset": academic_index,
            "academic_week_index": academic_index,
            "academic_week_number": int(pos["academic_week_number"]),
            "calendar_week_offset": int(pos["calendar_week_offset"]),
            "monday": str(pos["monday"]),
        }

    _WEEK_INFO_CACHE[cache_key] = dict(result)
    return result


def _parse_hhmm(value: str) -> dtime:
    hh, mm = value.split(":", 1)
    return dtime(int(hh), int(mm))


def _seconds_between(a: dtime, b: dtime) -> int:
    da = datetime.combine(date.today(), a)
    db = datetime.combine(date.today(), b)
    return max(0, int((db - da).total_seconds()))


def _last_actual_lesson(day_obj: dict[str, Any]) -> int:
    max_lesson = 0
    for class_name in CLASS_ORDER:
        lessons = day_obj.get(class_name, {})
        if not isinstance(lessons, dict):
            continue
        for key in lessons.keys():
            try:
                max_lesson = max(max_lesson, int(key))
            except Exception:
                pass
    return max_lesson


def resolve_period(
    now_t: dtime, bells: list[dict[str, Any]], last_actual: int
) -> dict[str, Any]:
    ordered: list[tuple[int, dtime, dtime]] = []
    for bell in bells:
        try:
            lesson = int(bell.get("lesson"))
            if 1 <= lesson <= last_actual:
                ordered.append(
                    (
                        lesson,
                        _parse_hhmm(str(bell["start"])),
                        _parse_hhmm(str(bell["end"])),
                    )
                )
        except Exception:
            pass
    ordered.sort()
    if not ordered:
        return {
            "phase": "NO_SCHEDULE",
            "lesson": 0,
            "in_lesson": False,
            "break_time": False,
            "after_school": False,
            "seconds_to_lesson_end": 0,
            "seconds_to_next_lesson": 0,
            "seconds_into_break": 0,
        }
    first_lesson, first_start, _ = ordered[0]
    if now_t < first_start:
        return {
            "phase": "BEFORE_SCHOOL",
            "lesson": first_lesson,
            "in_lesson": False,
            "break_time": False,
            "after_school": False,
            "seconds_to_lesson_end": 0,
            "seconds_to_next_lesson": _seconds_between(now_t, first_start),
            "seconds_into_break": 0,
        }
    previous = None
    for lesson, start, end in ordered:
        if start <= now_t <= end:
            return {
                "phase": "LESSON",
                "lesson": lesson,
                "in_lesson": True,
                "break_time": False,
                "after_school": False,
                "seconds_to_lesson_end": _seconds_between(now_t, end),
                "lesson_duration_seconds": _seconds_between(start, end),
                "seconds_to_next_lesson": 0,
                "seconds_into_break": 0,
            }
        if previous is not None:
            prev_lesson, _, prev_end = previous
            if prev_end < now_t < start:
                return {
                    "phase": "BREAK",
                    "lesson": lesson,
                    "in_lesson": False,
                    "break_time": True,
                    "after_school": False,
                    "seconds_to_lesson_end": 0,
                    "seconds_to_next_lesson": _seconds_between(now_t, start),
                    "seconds_into_break": _seconds_between(prev_end, now_t),
                }
        previous = (lesson, start, end)
    last_lesson, _, last_end = ordered[-1]
    if now_t > last_end:
        return {
            "phase": "AFTER_SCHOOL",
            "lesson": last_lesson,
            "in_lesson": False,
            "break_time": False,
            "after_school": True,
            "seconds_to_lesson_end": 0,
            "seconds_to_next_lesson": 0,
            "seconds_into_break": 0,
        }
    return {
        "phase": "NO_SCHEDULE",
        "lesson": last_lesson,
        "in_lesson": False,
        "break_time": False,
        "after_school": False,
        "seconds_to_lesson_end": 0,
        "seconds_to_next_lesson": 0,
        "seconds_into_break": 0,
    }


def _strip_group(value: str) -> tuple[str, str]:
    value = str(value or "").strip()
    m = GROUP_RE.match(value)
    if not m:
        return "", value
    return f"ГР. {m.group(1)}", GROUP_RE.sub("", value).strip()


_TEACHER_TWO_INITIALS_RE = re.compile(
    r"^(?P<surname>.+?[^\W\d_])\s*(?P<i1>[A-ZА-ЯІЇЄҐ])[\s.]+(?P<i2>[A-ZА-ЯІЇЄҐ])\.{0,3}$",
    re.U,
)
_TEACHER_ONE_INITIAL_RE = re.compile(
    r"^(?P<surname>.+?[^\W\d_])\s+(?P<i1>[A-ZА-ЯІЇЄҐ])\.{0,3}$",
    re.U,
)


def normalize_teacher_name(value: Any) -> str:
    """Normalize a teacher label without changing the surname.

    Examples:
      "Балог В.А"                -> "Балог В.А."
      "Харченко А О."            -> "Харченко А.О."
      "гр.2: КонстантіноваО.А."  -> "Константінова О.А."
      "Прибора Р.І.."            -> "Прибора Р.І."
      "Самойленко"               -> "Самойленко"

    The function is used by TV, Mobile/PWA, Teacher View and Operations so
    initials are rendered consistently everywhere.
    """
    _, text = _strip_group(str(value or ""))
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n:-–—")
    if not text:
        return ""

    m = _TEACHER_TWO_INITIALS_RE.match(text)
    if m:
        surname = re.sub(r"\s+", " ", m.group("surname")).strip(" .:-–—")
        return f"{surname} {m.group('i1')}.{m.group('i2')}."

    m = _TEACHER_ONE_INITIAL_RE.match(text)
    if m:
        surname = re.sub(r"\s+", " ", m.group("surname")).strip(" .:-–—")
        return f"{surname} {m.group('i1')}."

    # Do not invent initials when the source contains only a surname/full name.
    return re.sub(r"\.{2,}$", ".", text)


def _structured_entries(entries: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not isinstance(entries, list):
        return out
    for item in entries:
        if not isinstance(item, dict):
            continue
        raw_values = [
            str(item.get("subject", "")),
            str(item.get("room", "")),
            str(item.get("teacher", "")),
        ]
        subgroup = str(item.get("subgroup", "")).strip().upper()
        cleaned = []
        for value in raw_values:
            sg, val = _strip_group(value)
            if not subgroup and sg:
                subgroup = sg
            cleaned.append(val)
        if any(cleaned):
            out.append(
                {
                    "subgroup": subgroup,
                    "subject": cleaned[0],
                    "room": cleaned[1],
                    "teacher": normalize_teacher_name(cleaned[2]),
                }
            )
    return out


def _matches(criterion: Any, actual: str) -> bool:
    c = str(criterion or "").strip()
    return not c or c.lower() == "all" or c == actual


def _substitution(
    content: dict[str, Any],
    day: date,
    day_key: str,
    week_label: str,
    class_name: str,
    lesson: int,
    shelter: bool,
) -> list[dict[str, Any]] | None:
    wanted_scope = "shelter" if shelter else "normal"
    for sub in content.get("substitutions", []) or []:
        if not isinstance(sub, dict) or not sub.get("active", False):
            continue
        if not _matches(sub.get("date"), day.isoformat()):
            continue
        if not _matches(str(sub.get("day", "")).upper(), day_key):
            continue
        w = str(sub.get("week", "all")).strip().upper()
        if w not in ("", "ALL", week_label):
            continue
        if not _matches(sub.get("class"), class_name):
            continue
        try:
            if int(sub.get("lesson", -1)) != lesson:
                continue
        except Exception:
            continue
        scope = str(sub.get("scope", "both")).strip().lower()
        if scope not in ("both", wanted_scope):
            continue
        entries = sub.get("entries", [])
        return entries if isinstance(entries, list) else []
    return None


def _date_in_range(today: date, start: str, end: str) -> bool:
    try:
        if start and today < date.fromisoformat(start):
            return False
    except Exception:
        pass
    try:
        if end and today > date.fromisoformat(end):
            return False
    except Exception:
        pass
    return True


def active_announcements(
    include_today_events: bool = False, now: datetime | None = None
) -> list[str]:
    content = read_content()
    now_local = now or local_now("Europe/Kyiv")
    today = now_local.date()
    ranked: list[tuple[int, str]] = []

    for item in content.get("announcements", []) or []:
        if isinstance(item, str):
            value = item.strip()
            if value:
                ranked.append((5, value))
            continue
        if not isinstance(item, dict) or not item.get("active", True):
            continue
        if not _date_in_range(
            today, str(item.get("valid_from", "")), str(item.get("valid_to", ""))
        ):
            continue
        title = str(item.get("title", "")).strip()
        message = str(item.get("message", "")).strip()
        combined = (
            f"{title} • {message}".strip(" •")
            if title and message
            else (message or title)
        )
        if combined:
            try:
                priority = int(item.get("priority", 5))
            except Exception:
                priority = 5
            ranked.append((priority, combined))

    for item in content.get("events", []) or []:
        if not isinstance(item, dict) or not item.get("active", True):
            continue
        if not event_display(item, now_local, include_upcoming=include_today_events):
            continue
        start_time = str(item.get("start_time", "")).strip()
        title = str(item.get("title", "")).strip()
        message = str(item.get("message", "")).strip()
        combined = f"ПОДІЯ {start_time or 'сьогодні'} • {title}" + (
            f" • {message}" if message else ""
        )
        if title:
            try:
                priority = int(item.get("priority", 5))
            except Exception:
                priority = 5
            ranked.append((priority, combined))

    ranked.sort(key=lambda x: (-x[0], x[1]))
    return [text for _, text in ranked]


def build_schedule(
    now: datetime, config: dict[str, Any], shelter: bool
) -> dict[str, Any]:
    day = now.date()
    wk = week_info(day, str(config.get("numerator_start_date", "2026-09-01")))
    base = {
        "date": day.isoformat(),
        "day_label": DAY_UA[now.weekday()],
        "week": wk,
        "shelter": shelter,
        "rows": [],
    }
    if now.weekday() not in DAY_KEYS:
        return {
            **base,
            "phase": "NO_SCHEDULE",
            "message": "Занять за розкладом немає",
            "lesson": 0,
            "break_time": False,
            "after_school": False,
            "seconds_to_lesson_end": 0,
            "seconds_to_next_lesson": 0,
            "seconds_into_break": 0,
        }
    holiday = holiday_label(day)
    if holiday:
        return {
            **base,
            "phase": "HOLIDAY",
            "message": holiday,
            "lesson": 0,
            "break_time": False,
            "after_school": False,
            "seconds_to_lesson_end": 0,
            "seconds_to_next_lesson": 0,
            "seconds_into_break": 0,
        }
    day_key = DAY_KEYS[now.weekday()]
    name = (
        ("shelter_" if shelter else "schedule_")
        + ("numerator" if wk["numerator"] else "denominator")
        + ".json"
    )
    root = read_json(name, copy=False)
    day_obj = (root.get("days") or {}).get(day_key, {})
    if not isinstance(day_obj, dict):
        day_obj = {}
    last_actual = _last_actual_lesson(day_obj)
    if last_actual <= 0:
        return {
            **base,
            "phase": "NO_SCHEDULE",
            "message": "Занять сьогодні немає",
            "lesson": 0,
            "break_time": False,
            "after_school": False,
            "seconds_to_lesson_end": 0,
            "seconds_to_next_lesson": 0,
            "seconds_into_break": 0,
        }
    period = resolve_period(
        now.time().replace(tzinfo=None), effective_bells(root), last_actual
    )
    lesson = int(period["lesson"])
    if period["phase"] == "AFTER_SCHOOL":
        return {**base, **period, "message": "Заняття завершено"}
    if lesson <= 0:
        return {**base, **period, "message": "Немає активного уроку"}

    content = read_content()
    rows = []
    for class_name in CLASS_ORDER:
        lessons = (
            day_obj.get(class_name, {})
            if isinstance(day_obj.get(class_name, {}), dict)
            else {}
        )
        entries = lessons.get(str(lesson), [])
        replacement = _substitution(
            content, day, day_key, wk["label"], class_name, lesson, shelter
        )
        is_substitution = replacement is not None
        if is_substitution:
            entries = replacement
        rows.append(
            {
                "className": class_name,
                "entries": _structured_entries(entries),
                "substitution": is_substitution,
            }
        )
    return {**base, **period, "rows": rows, "message": ""}
