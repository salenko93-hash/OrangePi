from __future__ import annotations
from media_library import MEDIA_LOCK, remove_unreferenced_url
from json_cache import load_json

import base64
import json
import os
import re
import threading
import time
import uuid
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from mobile_api import build_mobile_schedule
from schedule_engine import (
    CLASS_ORDER,
    DAY_UA,
    effective_bells,
    normalize_teacher_name,
    read_content,
    read_json,
    week_info,
)
from timezone_utils import local_now

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PUBLIC = ROOT / "public"
MEDIA_DIR = PUBLIC / "media"
OPS_PATH = DATA / "smart_ops.json"
DEFAULT_PATH = DATA / "default" / "smart_ops.json"
_LOCK = threading.RLock()

KINDS = {
    "notification": "notifications",
    "media": "media",
    "signage": "signage_rules",
    "audio": "audio_events",
    "music": "music_tracks",
    "campus": "campuses",
}
_ALLOWED_MEDIA = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".mp4",
    ".webm",
    ".mp3",
    ".wav",
    ".ogg",
    ".m4a",
}
_MAX_MEDIA = 35 * 1024 * 1024
_TEACHER_GROUP = re.compile(r"^(?:гр\.?|група|підгрупа)\s*\d+\s*:?\s*", re.I | re.U)


def _now_dt() -> datetime:
    return local_now("Europe/Kyiv")


def _now_iso() -> str:
    return _now_dt().isoformat(timespec="seconds")


def _clean(value: Any, limit: int = 500) -> str:
    return " ".join(str(value or "").replace("\x00", "").split())[:limit]


def _bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off", ""}


def _int(
    value: Any, default: int = 0, minimum: int | None = None, maximum: int | None = None
) -> int:
    try:
        n = int(value)
    except Exception:
        n = default
    if minimum is not None:
        n = max(minimum, n)
    if maximum is not None:
        n = min(maximum, n)
    return n


def _atomic(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _default() -> dict[str, Any]:
    try:
        obj = load_json(DEFAULT_PATH)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    return {
        "notifications": [],
        "media": [],
        "signage_rules": [],
        "audio_events": [],
        "music_tracks": [],
        "campuses": [],
    }


def load_ops() -> dict[str, Any]:
    with MEDIA_LOCK, _LOCK:
        if not OPS_PATH.exists():
            _atomic(OPS_PATH, _default())
        try:
            obj = load_json(OPS_PATH)
        except Exception:
            obj = {}
        default = _default()
        return {
            key: list(obj.get(key, default.get(key, [])))
            if isinstance(obj.get(key, default.get(key, [])), list)
            else []
            for key in default
        }


def save_ops(obj: dict[str, Any]) -> dict[str, Any]:
    with MEDIA_LOCK, _LOCK:
        default = _default()
        clean = {
            key: list(obj.get(key, [])) if isinstance(obj.get(key, []), list) else []
            for key in default
        }
        _atomic(OPS_PATH, clean)
        return clean


def _date_active(item: dict[str, Any], today: date | None = None) -> bool:
    today = today or _now_dt().date()
    iso = today.isoformat()
    start = _clean(item.get("valid_from") or item.get("date_from"), 20)
    end = _clean(item.get("valid_to") or item.get("date_to"), 20)
    if start and iso < start:
        return False
    if end and iso > end:
        return False
    single = _clean(item.get("date"), 20)
    if single and single != iso:
        return False
    return True


def _time_active(item: dict[str, Any], now: datetime | None = None) -> bool:
    now = now or _now_dt()
    hhmm = now.strftime("%H:%M")
    start = _clean(item.get("start_time"), 10)
    end = _clean(item.get("end_time"), 10)
    if start and hhmm < start:
        return False
    if end and hhmm > end:
        return False
    days = item.get("days", [])
    if isinstance(days, list) and days:
        wanted = {str(x).strip().upper() for x in days}
        day_key = [
            "MONDAY",
            "TUESDAY",
            "WEDNESDAY",
            "THURSDAY",
            "FRIDAY",
            "SATURDAY",
            "SUNDAY",
        ][now.weekday()]
        if day_key not in wanted and str(now.weekday()) not in wanted:
            return False
    return True


def normalize(kind: str, item: dict[str, Any]) -> dict[str, Any]:
    kind = str(kind or "").strip().lower()
    if kind not in KINDS:
        raise ValueError("Невідомий Smart Operations тип")
    item = item if isinstance(item, dict) else {}
    base = {
        "id": _clean(item.get("id"), 80) or uuid.uuid4().hex[:12],
        "active": _bool(item.get("active"), True),
        "updated_at": _now_iso(),
    }
    if kind == "notification":
        audience = _clean(item.get("audience"), 20).lower() or "all"
        if audience not in {"all", "class", "teacher", "screen"}:
            audience = "all"
        base.update(
            {
                "seq": _int(item.get("seq"), int(time.time() * 1000), 1),
                "title": _clean(item.get("title"), 120) or "LyceumTV",
                "message": _clean(item.get("message"), 800),
                "level": _clean(item.get("level"), 20).lower() or "info",
                "audience": audience,
                "target": _clean(item.get("target"), 120),
                "valid_from": _clean(item.get("valid_from"), 20),
                "valid_to": _clean(item.get("valid_to"), 20),
                "source": _clean(item.get("source"), 80) or "manual",
                "created_at": _clean(item.get("created_at"), 40) or _now_iso(),
            }
        )
        if not base["message"]:
            raise ValueError("Вкажіть текст сповіщення")
    elif kind == "media":
        media_kind = _clean(item.get("media_kind"), 20).lower() or "image"
        if media_kind not in {"image", "video", "text"}:
            media_kind = "image"
        base.update(
            {
                "title": _clean(item.get("title"), 120),
                "message": _clean(item.get("message"), 1000),
                "media_kind": media_kind,
                "after_school_slideshow": media_kind in {"image", "video"}
                and _bool(item.get("after_school_slideshow"), False),
                "url": _clean(item.get("url"), 500),
                "duration": _int(item.get("duration"), 12, 3, 300),
                "valid_from": _clean(item.get("valid_from"), 20),
                "valid_to": _clean(item.get("valid_to"), 20),
                "start_time": _clean(item.get("start_time"), 10),
                "end_time": _clean(item.get("end_time"), 10),
                "days": list(item.get("days", []))
                if isinstance(item.get("days"), list)
                else [],
                "priority": _int(item.get("priority"), 5, 0, 9),
            }
        )
        if not (base["title"] or base["message"] or base["url"]):
            raise ValueError("Медіа-картка порожня")
    elif kind == "signage":
        mode = _clean(item.get("mode"), 20).lower() or "schedule"
        if mode not in {"schedule", "media", "events", "welcome"}:
            mode = "schedule"
        base.update(
            {
                "name": _clean(item.get("name"), 120) or "Правило Digital Signage",
                "mode": mode,
                "media_id": _clean(item.get("media_id"), 80),
                "start_time": _clean(item.get("start_time"), 10),
                "end_time": _clean(item.get("end_time"), 10),
                "valid_from": _clean(item.get("valid_from"), 20),
                "valid_to": _clean(item.get("valid_to"), 20),
                "days": list(item.get("days", []))
                if isinstance(item.get("days"), list)
                else [],
                "priority": _int(item.get("priority"), 5, 0, 9),
                "screen": _clean(item.get("screen"), 80) or "all",
            }
        )
    elif kind == "audio":
        days = item.get("days", [])
        permitted_days = {
            "MONDAY",
            "TUESDAY",
            "WEDNESDAY",
            "THURSDAY",
            "FRIDAY",
            "SATURDAY",
            "SUNDAY",
        }
        if (
            not isinstance(days, list)
            or len(days) > 7
            or any(
                not isinstance(day, str) or day not in permitted_days for day in days
            )
        ):
            raise ValueError("Некоректні дні аудіоподії")
        base.update(
            {
                "name": _clean(item.get("name"), 120) or "Аудіоподія",
                "time": _clean(item.get("time"), 10),
                "days": list(item.get("days", []))
                if isinstance(item.get("days"), list)
                else [],
                "url": _clean(item.get("url"), 500),
                "volume": max(0.0, min(1.0, float(item.get("volume", 0.8) or 0.8))),
                "once_per_day": _bool(item.get("once_per_day"), True),
            }
        )
        if not base["time"] or not base["url"]:
            raise ValueError("Для аудіоподії потрібні час і файл")
    elif kind == "music":
        playlist = _clean(item.get("playlist"), 30).lower() or "both"
        if playlist not in {"break", "after_school", "both"}:
            playlist = "both"
        base.update(
            {
                "title": _clean(item.get("title"), 160) or "Музичний трек",
                "artist": _clean(item.get("artist"), 160),
                "url": _clean(item.get("url"), 500),
                "playlist": playlist,
                "order": _int(item.get("order"), 100, 0, 9999),
            }
        )
        if not base["url"]:
            raise ValueError("Для музичного треку потрібен URL/файл")
    else:
        floors = item.get("floors", [])
        if isinstance(floors, str):
            floors = [x.strip() for x in floors.split(",") if x.strip()]
        base.update(
            {
                "name": _clean(item.get("name"), 120) or "Корпус",
                "address": _clean(item.get("address"), 220),
                "floors": [str(x)[:20] for x in floors[:30]]
                if isinstance(floors, list)
                else [],
            }
        )
    return base


def upsert(kind: str, item: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize(kind, item)
    key = KINDS[kind]
    with MEDIA_LOCK, _LOCK:
        data = load_ops()
        arr = data[key]
        for i, old in enumerate(arr):
            if isinstance(old, dict) and str(old.get("id")) == normalized["id"]:
                arr[i] = normalized
                break
        else:
            arr.append(normalized)
        data[key] = arr
        save_ops(data)
    return normalized


def delete(kind: str, item_id: str) -> bool:
    kind = str(kind or "").strip().lower()
    if kind not in KINDS:
        raise ValueError("Невідомий Smart Operations тип")
    with MEDIA_LOCK, _LOCK:
        data = load_ops()
        key = KINDS[kind]
        removed = [
            item
            for item in data[key]
            if isinstance(item, dict) and str(item.get("id")) == str(item_id)
        ]
        before = len(data[key])
        data[key] = [
            x
            for x in data[key]
            if not (isinstance(x, dict) and str(x.get("id")) == str(item_id))
        ]
        save_ops(data)
        if kind in {"media", "music", "audio"}:
            for item in removed:
                remove_unreferenced_url(item.get("url", ""), ROOT)
        return len(data[key]) != before


def notify_from_substitution(item: dict[str, Any]) -> dict[str, Any]:
    entries = item.get("entries", []) if isinstance(item, dict) else []
    details = []
    for e in entries:
        if isinstance(e, dict):
            subject = _clean(e.get("subject"), 120)
            room = _clean(e.get("room"), 40)
            text = subject + (f" • каб. {room}" if room else "")
            if text:
                details.append(text)
    cls = _clean(item.get("class"), 20)
    lesson = _int(item.get("lesson"), 0)
    d = _clean(item.get("date"), 20)
    note = _clean(item.get("note"), 180)
    msg = f"{d}: {cls}, {lesson} урок — " + "; ".join(details)
    if note:
        msg += f". {note}"
    return upsert(
        "notification",
        {
            "id": f"auto-sub-{_clean(item.get('id'), 60)}",
            "active": item.get("active", True),
            "title": "Заміна в розкладі",
            "message": msg,
            "level": "warning",
            "audience": "class",
            "target": cls,
            "valid_from": d,
            "valid_to": d,
            "source": "substitution",
        },
    )


def notify_from_announcement(item: dict[str, Any]) -> dict[str, Any]:
    return upsert(
        "notification",
        {
            "id": f"auto-ann-{_clean(item.get('id'), 60)}",
            "active": item.get("active", True),
            "title": _clean(item.get("title"), 120) or "Оголошення",
            "message": _clean(item.get("message"), 800),
            "level": "info",
            "audience": "all",
            "valid_from": _clean(item.get("valid_from"), 20),
            "valid_to": _clean(item.get("valid_to"), 20),
            "source": "announcement",
        },
    )


def notifications_for(
    *,
    class_name: str = "",
    teacher: str = "",
    screen: str = "",
    after: int = 0,
    limit: int = 50,
) -> list[dict[str, Any]]:
    today = _now_dt().date()
    out = []
    for item in load_ops().get("notifications", []):
        if not isinstance(item, dict) or item.get("active", True) is False:
            continue
        if not _date_active(item, today):
            continue
        seq = _int(item.get("seq"), 0)
        if seq <= int(after or 0):
            continue
        audience = str(item.get("audience") or "all")
        target = str(item.get("target") or "")
        if audience == "class" and target != class_name:
            continue
        if audience == "teacher" and target != teacher:
            continue
        if audience == "screen" and target != screen:
            continue
        out.append(dict(item))
    out.sort(key=lambda x: int(x.get("seq") or 0))
    return out[-max(1, min(100, int(limit or 50))) :]


def _teacher_name(raw: Any) -> str:
    return normalize_teacher_name(
        _TEACHER_GROUP.sub("", _clean(raw, 120)).strip(" :-–—")
    )


def _schedule_roots() -> list[dict[str, Any]]:
    roots = []
    for name in ("schedule_numerator.json", "schedule_denominator.json"):
        try:
            roots.append(read_json(name, copy=False))
        except Exception:
            pass
    return roots


def directory() -> dict[str, list[str]]:
    teachers, rooms, subjects = set(), set(), set()
    for root in _schedule_roots():
        for day_obj in (root.get("days") or {}).values():
            if not isinstance(day_obj, dict):
                continue
            for cls_obj in day_obj.values():
                if not isinstance(cls_obj, dict):
                    continue
                for entries in cls_obj.values():
                    if not isinstance(entries, list):
                        continue
                    for e in entries:
                        if not isinstance(e, dict):
                            continue
                        teacher = _teacher_name(e.get("teacher"))
                        room = _clean(e.get("room"), 40)
                        subject = _clean(e.get("subject"), 120)
                        if teacher:
                            teachers.add(teacher)
                        if room and room not in {"—", "-"}:
                            rooms.add(room)
                        if subject:
                            subjects.add(subject)
    return {
        "teachers": sorted(teachers),
        "rooms": sorted(rooms, key=lambda x: (not str(x).isdigit(), str(x))),
        "subjects": sorted(subjects),
        "classes": list(CLASS_ORDER),
    }


def teacher_schedule(teacher: str, day: date, cfg: dict[str, Any]) -> dict[str, Any]:
    teacher = _clean(teacher, 120)
    lessons = []
    for cls in CLASS_ORDER:
        mobile = build_mobile_schedule(cls, day, cfg)
        for lesson in mobile.get("lessons", []):
            for entry in lesson.get("entries", []):
                if _teacher_name(entry.get("teacher")) != teacher:
                    continue
                lessons.append(
                    {
                        "lesson": lesson.get("lesson"),
                        "start": lesson.get("start", ""),
                        "end": lesson.get("end", ""),
                        "class": cls,
                        "subject": entry.get("subject", ""),
                        "room": entry.get("room", ""),
                        "subgroup": entry.get("subgroup", ""),
                        "substitution": bool(lesson.get("substitution")),
                    }
                )
    lessons.sort(key=lambda x: (int(x.get("lesson") or 99), x.get("class", "")))
    return {
        "ok": True,
        "teacher": teacher,
        "date": day.isoformat(),
        "day_label": DAY_UA.get(day.weekday(), ""),
        "lessons": lessons,
    }


def room_schedule(room: str, day: date, cfg: dict[str, Any]) -> dict[str, Any]:
    room = _clean(room, 40)
    lessons = []
    for cls in CLASS_ORDER:
        mobile = build_mobile_schedule(cls, day, cfg)
        for lesson in mobile.get("lessons", []):
            for entry in lesson.get("entries", []):
                if _clean(entry.get("room"), 40) != room:
                    continue
                lessons.append(
                    {
                        "lesson": lesson.get("lesson"),
                        "start": lesson.get("start", ""),
                        "end": lesson.get("end", ""),
                        "class": cls,
                        "subject": entry.get("subject", ""),
                        "teacher": _teacher_name(entry.get("teacher")),
                        "subgroup": entry.get("subgroup", ""),
                        "substitution": bool(lesson.get("substitution")),
                    }
                )
    lessons.sort(key=lambda x: (int(x.get("lesson") or 99), x.get("class", "")))
    return {"ok": True, "room": room, "date": day.isoformat(), "lessons": lessons}


def free_rooms(day: date, lesson_number: int, cfg: dict[str, Any]) -> dict[str, Any]:
    catalog = set(
        str(x).strip() for x in (cfg.get("room_catalog") or []) if str(x).strip()
    )
    catalog.update(directory()["rooms"])
    used: dict[str, list[dict[str, str]]] = {}
    for cls in CLASS_ORDER:
        mobile = build_mobile_schedule(cls, day, cfg)
        for lesson in mobile.get("lessons", []):
            if int(lesson.get("lesson") or 0) != int(lesson_number):
                continue
            for entry in lesson.get("entries", []):
                room = _clean(entry.get("room"), 40)
                if not room:
                    continue
                used.setdefault(room, []).append(
                    {
                        "class": cls,
                        "subject": _clean(entry.get("subject"), 120),
                        "teacher": _teacher_name(entry.get("teacher")),
                    }
                )
    free = sorted(
        [x for x in catalog if x not in used],
        key=lambda x: (not str(x).isdigit(), str(x)),
    )
    return {
        "ok": True,
        "date": day.isoformat(),
        "lesson": int(lesson_number),
        "free": free,
        "used": used,
        "total": len(catalog),
    }


def campus_stats(cfg: dict[str, Any]) -> dict[str, Any]:
    teacher_load, room_load, subject_load = Counter(), Counter(), Counter()
    total_entries = 0
    for root in _schedule_roots():
        for day_obj in (root.get("days") or {}).values():
            if not isinstance(day_obj, dict):
                continue
            for cls_obj in day_obj.values():
                if not isinstance(cls_obj, dict):
                    continue
                for entries in cls_obj.values():
                    if not isinstance(entries, list):
                        continue
                    for e in entries:
                        if not isinstance(e, dict):
                            continue
                        total_entries += 1
                        t = _teacher_name(e.get("teacher"))
                        r = _clean(e.get("room"), 40)
                        s = _clean(e.get("subject"), 120)
                        if t:
                            teacher_load[t] += 1
                        if r:
                            room_load[r] += 1
                        if s:
                            subject_load[s] += 1
    content = read_content()
    substitutions = [
        x
        for x in content.get("substitutions", [])
        if isinstance(x, dict) and x.get("active", False)
    ]
    return {
        "total_schedule_entries_two_weeks": total_entries,
        "teachers": len(teacher_load),
        "rooms": len(room_load),
        "subjects": len(subject_load),
        "active_substitutions": len(substitutions),
        "top_teachers": teacher_load.most_common(10),
        "top_rooms": room_load.most_common(10),
        "top_subjects": subject_load.most_common(10),
    }


def health_alerts(
    system: dict[str, Any],
    screens: list[dict[str, Any]],
    state: dict[str, Any],
    cfg: dict[str, Any],
) -> list[dict[str, str]]:
    alerts = []
    temp = system.get("cpu_temp_c")
    if temp is not None and float(temp) >= float(
        cfg.get("health_cpu_warn_c", 75) or 75
    ):
        alerts.append(
            {
                "level": "warning",
                "code": "cpu_temp",
                "message": f"Температура CPU {temp} °C",
            }
        )
    disk = system.get("disk") or {}
    if disk.get("total"):
        pct = round(float(disk.get("used", 0)) * 100 / float(disk["total"]), 1)
        if pct >= float(cfg.get("health_disk_warn_percent", 90) or 90):
            alerts.append(
                {
                    "level": "warning",
                    "code": "disk",
                    "message": f"Диск заповнено на {pct}%",
                }
            )
    mem = system.get("memory") or {}
    if mem.get("total"):
        pct = round(float(mem.get("used", 0)) * 100 / float(mem["total"]), 1)
        if pct >= float(cfg.get("health_memory_warn_percent", 90) or 90):
            alerts.append(
                {
                    "level": "warning",
                    "code": "memory",
                    "message": f"RAM використано {pct}%",
                }
            )
    offline = [x for x in screens if not x.get("online")]
    if offline:
        alerts.append(
            {
                "level": "warning",
                "code": "screens",
                "message": f"Екранів offline: {len(offline)}",
            }
        )
    sync = state.get("sync") or {}
    if sync.get("ok") is False:
        alerts.append(
            {
                "level": "error",
                "code": "sync",
                "message": "Помилка синхронізації контенту",
            }
        )
    return alerts


def slideshow_url(value: Any) -> str:
    url = str(value or "").strip()
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    local = url.startswith("/media/") and not parsed.netloc and not parsed.scheme
    remote = (
        parsed.scheme == "https"
        and bool(parsed.netloc)
        and not parsed.username
        and not parsed.password
    )
    return url if local or remote else ""


def after_school_slides(now: datetime | None = None) -> dict[str, Any]:
    """Explicitly selected photos first, then full-length videos, in library order."""
    now = now or _now_dt()
    items = []
    for item in load_ops().get("media", []):
        if not isinstance(item, dict) or not _bool(item.get("active"), True):
            continue
        kind = item.get("media_kind")
        if kind not in {"image", "video"} or not _bool(
            item.get("after_school_slideshow"), False
        ):
            continue
        if not _date_active(item, now.date()) or not _time_active(item, now):
            continue
        url = slideshow_url(item.get("url"))
        if url:
            items.append({"id": str(item.get("id") or ""), "url": url, "kind": kind})
    items.sort(key=lambda item: item["kind"] == "video")
    count = sum(item["kind"] == "image" for item in items)
    return {
        "ok": True,
        "interval_seconds": 3,
        "items": items,
        "photo_count": count,
        "photo_duration_seconds": count * 3,
    }


def signage_current(
    cfg: dict[str, Any], screen_id: str = "main-hall", now: datetime | None = None
) -> dict[str, Any]:
    now = now or _now_dt()
    if not cfg.get("signage_enabled", True):
        return {"ok": True, "mode": "schedule", "rule": None, "media": None}
    data = load_ops()
    rules = []
    for item in data.get("signage_rules", []):
        if not isinstance(item, dict) or item.get("active", True) is False:
            continue
        if str(item.get("screen") or "all") not in {"all", screen_id}:
            continue
        if not _date_active(item, now.date()) or not _time_active(item, now):
            continue
        rules.append(item)
    rules.sort(key=lambda x: int(x.get("priority") or 0), reverse=True)
    if not rules:
        return {"ok": True, "mode": "schedule", "rule": None, "media": None}
    rule = rules[0]
    media = None
    if rule.get("media_id"):
        media = next(
            (
                x
                for x in data.get("media", [])
                if isinstance(x, dict)
                and x.get("id") == rule.get("media_id")
                and x.get("active", True) is not False
            ),
            None,
        )
    return {
        "ok": True,
        "mode": rule.get("mode", "schedule"),
        "rule": rule,
        "media": media,
    }


def audio_current(cfg: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = now or _now_dt()
    if not cfg.get("audio_events_enabled", True):
        return {"ok": True, "event": None}
    hhmm = now.strftime("%H:%M")
    day_key = [
        "MONDAY",
        "TUESDAY",
        "WEDNESDAY",
        "THURSDAY",
        "FRIDAY",
        "SATURDAY",
        "SUNDAY",
    ][now.weekday()]
    for item in load_ops().get("audio_events", []):
        if not isinstance(item, dict) or item.get("active", True) is False:
            continue
        days = {str(x).strip().upper() for x in item.get("days", []) or []}
        if days and day_key not in days:
            continue
        if str(item.get("time") or "") == hhmm:
            return {
                "ok": True,
                "event": item,
                "event_key": f"{now.date().isoformat()}:{item.get('id')}:{hhmm}",
            }
    return {"ok": True, "event": None}


def music_state(
    cfg: dict[str, Any], state: dict[str, Any], now: datetime | None = None
) -> dict[str, Any]:
    """Return the desired background-music policy for the TV kiosk.

    Priority: AIR_RAID/SILENCE/ALL_CLEAR and scheduled audio always win.
    Music is only eligible on BREAK or AFTER_SCHOOL before the configured cutoff.
    """
    now = now or _now_dt()
    mode = str((state or {}).get("mode") or "NORMAL")
    schedule = (state or {}).get("schedule") or {}
    phase = str(schedule.get("phase") or "")
    until = _clean(cfg.get("music_after_school_until"), 10) or "18:00"
    volume = max(0, min(100, _int(cfg.get("music_volume_percent"), 35, 0, 100))) / 100.0
    fade = max(0, min(20, _int(cfg.get("music_fade_seconds"), 2, 0, 20)))
    break_fade = max(
        0, min(180, _int(cfg.get("music_break_fade_before_end_seconds"), 30, 0, 180))
    )

    result = {
        "ok": True,
        "enabled": bool(cfg.get("music_enabled", True)),
        "allowed": False,
        "reason": "",
        "mode": mode,
        "phase": phase,
        "playlist": "",
        "tracks": [],
        "volume": volume,
        "shuffle": bool(cfg.get("music_shuffle", True)),
        "fade_seconds": fade,
        "break_fade_before_end_seconds": break_fade,
        "seconds_to_next_lesson": int(schedule.get("seconds_to_next_lesson", 0) or 0),
        "after_school_until": until,
    }

    if not result["enabled"]:
        result["reason"] = "disabled"
        return result

    if mode != "NORMAL":
        result["reason"] = "priority_mode"
        return result

    if audio_current(cfg, now).get("event"):
        result["reason"] = "system_audio"
        return result

    playlist = ""
    if phase == "BREAK" and bool(cfg.get("music_breaks_enabled", True)):
        playlist = "break"
    elif phase == "AFTER_SCHOOL" and bool(cfg.get("music_after_school_enabled", True)):
        if now.strftime("%H:%M") < until:
            playlist = "after_school"
        else:
            result["reason"] = "after_school_cutoff"
            return result
    else:
        result["reason"] = "not_music_time"
        return result

    tracks = []
    for item in load_ops().get("music_tracks", []):
        if not isinstance(item, dict) or item.get("active", True) is False:
            continue
        target = str(item.get("playlist") or "both")
        if target not in {"both", playlist}:
            continue
        if not str(item.get("url") or "").strip():
            continue
        tracks.append(
            {
                "id": str(item.get("id") or ""),
                "title": str(item.get("title") or "Музичний трек"),
                "artist": str(item.get("artist") or ""),
                "url": str(item.get("url") or ""),
                "playlist": target,
                "order": int(item.get("order") or 100),
            }
        )

    tracks.sort(key=lambda x: (x["order"], x["title"].lower(), x["id"]))
    result["playlist"] = playlist
    result["tracks"] = tracks
    if not tracks:
        result["reason"] = "no_tracks"
        return result

    result["allowed"] = True
    result["reason"] = "break" if playlist == "break" else "after_school"
    return result


def save_media_upload(file_name: str, data_base64: str) -> dict[str, Any]:
    name = Path(str(file_name or "media.bin")).name
    ext = Path(name).suffix.lower()
    if ext not in _ALLOWED_MEDIA:
        raise ValueError("Дозволено PNG/JPG/WEBP/MP4/WEBM/MP3/WAV/OGG/M4A")
    raw_text = str(data_base64 or "")
    if "," in raw_text and raw_text.lstrip().startswith("data:"):
        raw_text = raw_text.split(",", 1)[1]
    try:
        raw = base64.b64decode(raw_text, validate=True)
    except Exception as exc:
        raise ValueError("Некоректний base64") from exc
    if not raw or len(raw) > _MAX_MEDIA:
        raise ValueError("Файл порожній або більший за 35 MB")
    import io
    from media_io import save_stream

    return save_stream(MEDIA_DIR, name, io.BytesIO(raw), len(raw))


def active_events(day: date | None = None) -> list[dict[str, Any]]:
    day = day or _now_dt().date()
    out = []
    for x in read_content().get("events", []) or []:
        if not isinstance(x, dict) or x.get("active", True) is False:
            continue
        if str(x.get("date") or "") and str(x.get("date")) != day.isoformat():
            continue
        out.append(dict(x))
    out.sort(
        key=lambda x: (
            str(x.get("date") or ""),
            str(x.get("start_time") or ""),
            -int(x.get("priority") or 0),
        )
    )
    return out


def public_campus(cfg: dict[str, Any]) -> dict[str, Any]:
    content = read_content()
    announcements = []
    today = _now_dt().date()
    for x in content.get("announcements", []) or []:
        if not isinstance(x, dict) or x.get("active", True) is False:
            continue
        if _date_active(x, today):
            announcements.append(
                {
                    "title": _clean(x.get("title"), 120),
                    "message": _clean(x.get("message"), 500),
                    "priority": _int(x.get("priority"), 5, 0, 9),
                }
            )
    announcements.sort(key=lambda x: -x["priority"])
    wk = week_info(today, str(cfg.get("numerator_start_date", "2026-09-01")))
    try:
        schedule_root = read_json(
            "schedule_" + ("numerator" if wk["numerator"] else "denominator") + ".json"
        )
        bells = effective_bells(schedule_root)
    except Exception:
        bells = []
    return {
        "ok": True,
        "name": str(cfg.get("campus_name") or "Lyceum Smart Campus"),
        "mobile_url": str(cfg.get("mobile_public_url") or "/mobile/"),
        "classes": list(CLASS_ORDER),
        "announcements": announcements[:10],
        "events": active_events(today)[:10],
        "week": wk,
        "bells": bells,
        "date": today.isoformat(),
    }
