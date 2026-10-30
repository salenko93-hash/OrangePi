from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from backup_manager import create_backup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
IMPORT_DIR = DATA / "imports"
STAGE_DIR = IMPORT_DIR / "staging"
HISTORY_DIR = IMPORT_DIR / "history"

TARGETS = {
    "schedule_numerator": "schedule_numerator.json",
    "schedule_denominator": "schedule_denominator.json",
    "shelter_numerator": "shelter_numerator.json",
    "shelter_denominator": "shelter_denominator.json",
}
CLASS_ORDER = ["10-А", "10-Б", "10-В", "10-Г", "11-А", "11-Б", "11-В", "11-Г"]
DAY_NAMES = {
    "ПОНЕДІЛОК": "MONDAY",
    "ВІВТОРОК": "TUESDAY",
    "СЕРЕДА": "WEDNESDAY",
    "ЧЕТВЕР": "THURSDAY",
    "П'ЯТНИЦЯ": "FRIDAY",
    "П’ЯТНИЦЯ": "FRIDAY",
    "СУБОТА": "SATURDAY",
}
DEFAULT_BELLS = [
    {"lesson": 1, "start": "08:00", "end": "08:45"},
    {"lesson": 2, "start": "08:55", "end": "09:40"},
    {"lesson": 3, "start": "09:55", "end": "10:40"},
    {"lesson": 4, "start": "10:50", "end": "11:35"},
    {"lesson": 5, "start": "11:45", "end": "12:30"},
    {"lesson": 6, "start": "12:40", "end": "13:25"},
    {"lesson": 7, "start": "13:35", "end": "14:20"},
    {"lesson": 8, "start": "14:30", "end": "15:15"},
]
_GROUP_RE = re.compile(
    r"^(?:гр\.?|група|підгрупа)\s*([0-9]+)\s*[:.]?\s*(.*)$", re.I | re.U
)


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)
    return re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip()


def _normalize_group_prefix(value: Any) -> str:
    text = _clean(value)
    m = _GROUP_RE.match(text)
    if not m:
        return text
    tail = m.group(2).strip()
    return f"гр.{m.group(1)}: {tail}".rstrip()


def _dedupe_repeat(value: Any) -> str:
    text = _clean(value)
    words = text.split()
    if len(words) >= 2 and len(words) % 2 == 0:
        half = len(words) // 2
        if [x.casefold() for x in words[:half]] == [x.casefold() for x in words[half:]]:
            return " ".join(words[:half])
    return text


def _norm_class(value: Any) -> str:
    text = _clean(value).replace("–", "-").replace("—", "-")
    return text.upper()


def _time_range(value: Any) -> tuple[str, str] | None:
    text = _clean(value)
    found = re.findall(r"(\d{1,2}:\d{2})", text)
    if len(found) < 2:
        return None

    def pad(t: str) -> str:
        hh, mm = t.split(":", 1)
        return f"{int(hh):02d}:{int(mm):02d}"

    return pad(found[0]), pad(found[1])


def _suggest_target(filename: str, title: str) -> str:
    text = (filename + " " + title).casefold()
    shelter = "укрит" in text
    denominator = "знамен" in text
    numerator = "чисель" in text
    if shelter and denominator:
        return "shelter_denominator"
    if shelter and numerator:
        return "shelter_numerator"
    if denominator:
        return "schedule_denominator"
    if numerator:
        return "schedule_numerator"
    return "schedule_denominator"


def _load_workbook(path: Path):
    try:
        from openpyxl import load_workbook
    except Exception as exc:
        raise RuntimeError("Потрібен пакет python3-openpyxl") from exc
    return load_workbook(path, data_only=True, read_only=True)


def parse_xlsx(path: Path, filename: str = "") -> tuple[dict[str, Any], dict[str, Any]]:
    wb = _load_workbook(path)
    ws = wb.active
    max_row = min(int(ws.max_row or 0), 5000)
    max_col = min(int(ws.max_column or 0), 128)
    if max_row < 3 or max_col < 6:
        raise ValueError("XLSX не схожий на таблицю розкладу")

    matrix = [
        list(row)
        for row in ws.iter_rows(
            min_row=1, max_row=max_row, min_col=1, max_col=max_col, values_only=True
        )
    ]

    def cell(row: int, col: int):
        if row < 1 or col < 1 or row > len(matrix) or col > len(matrix[row - 1]):
            return None
        return matrix[row - 1][col - 1]

    header_rows = min(max_row, 12)
    day_cols: dict[str, int] = {}
    title_parts: list[str] = []
    for r in range(1, header_rows + 1):
        for c in range(1, max_col + 1):
            value = _clean(cell(r, c))
            if not value:
                continue
            if r <= 2:
                title_parts.append(value)
            key = value.upper()
            if key in DAY_NAMES and DAY_NAMES[key] not in day_cols:
                day_cols[DAY_NAMES[key]] = c

    expected_days = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"]
    missing_days = [x for x in expected_days if x not in day_cols]
    if missing_days:
        raise ValueError("Не знайдено колонки днів: " + ", ".join(missing_days))

    title = " • ".join(title_parts[:8])
    suggested_target = _suggest_target(filename, title)

    # Determine the first timetable data row: first row that has a supported class in column A.
    first_data_row = None
    for r in range(1, max_row + 1):
        if _norm_class(cell(r, 1)) in CLASS_ORDER:
            first_data_row = r
            break
    if first_data_row is None:
        raise ValueError("Не знайдено класи 10-А … 11-Г у колонці A")

    days = {day: {name: {} for name in CLASS_ORDER} for day in expected_days}
    warnings: list[str] = []
    errors: list[str] = []
    source_classes: set[str] = set()
    ignored_room_only = 0
    recovered_subjects = 0
    duplicates_over_two = 0
    current_class = ""
    current_lesson = 0
    bells_by_lesson: dict[int, tuple[str, str]] = {}

    for r in range(first_data_row, max_row + 1):
        class_raw = _norm_class(cell(r, 1))
        if class_raw:
            if class_raw in CLASS_ORDER:
                current_class = class_raw
                source_classes.add(class_raw)
            elif re.match(r"^(10|11)-", class_raw):
                warnings.append(f"Рядок {r}: невідомий клас «{class_raw}»")
                current_class = ""
                continue

        if not current_class:
            continue

        time_pair = _time_range(cell(r, 2))

        lesson_candidates: list[int] = []
        for day in expected_days:
            c = day_cols[day]
            raw = cell(r, c)
            try:
                n = int(raw) if raw not in (None, "") else 0
            except Exception:
                n = 0
            if 1 <= n <= 12:
                lesson_candidates.append(n)

        if lesson_candidates:
            current_lesson = lesson_candidates[0]
            if len(set(lesson_candidates)) > 1:
                warnings.append(
                    f"Рядок {r}: різні номери уроку по днях {lesson_candidates}"
                )
        elif time_pair:
            # Infer lesson by observed time position when the day-number cells are empty.
            current_lesson = current_lesson or 1

        if current_lesson <= 0:
            continue

        if time_pair:
            bells_by_lesson[current_lesson] = time_pair

        for day in expected_days:
            c = day_cols[day]
            subject = _normalize_group_prefix(_dedupe_repeat(cell(r, c + 1)))
            room = _clean(cell(r, c + 2))
            teacher = _normalize_group_prefix(cell(r, c + 3))

            if not subject and not teacher:
                if room:
                    ignored_room_only += 1
                continue

            lesson_key = str(current_lesson)
            arr = days[day][current_class].setdefault(lesson_key, [])

            # Visually merged/grouped source cells may have subject only on the previous row.
            if not subject and teacher and arr:
                subject = str(arr[-1].get("subject", ""))
                recovered_subjects += 1

            if not subject:
                warnings.append(
                    f"Рядок {r}: {day} {current_class} {current_lesson} урок — є викладач, але немає предмета"
                )

            item = {"subject": subject, "room": room, "teacher": teacher}
            if item not in arr:
                arr.append(item)
            if len(arr) > 2:
                duplicates_over_two += 1

    missing_classes = [c for c in CLASS_ORDER if c not in source_classes]
    if missing_classes:
        errors.append("Немає класів: " + ", ".join(missing_classes))

    bell_schedule = []
    for n in range(1, 9):
        if n in bells_by_lesson:
            start, end = bells_by_lesson[n]
            bell_schedule.append({"lesson": n, "start": start, "end": end})
        else:
            bell_schedule.append(dict(DEFAULT_BELLS[n - 1]))

    entry_count = sum(
        len(entries)
        for day in days.values()
        for lessons in day.values()
        for entries in lessons.values()
    )
    occupied_lessons = sum(
        1
        for day in days.values()
        for lessons in day.values()
        for entries in lessons.values()
        if entries
    )
    if entry_count == 0:
        errors.append("У XLSX не знайдено жодного уроку")
    if duplicates_over_two:
        warnings.append(
            f"{duplicates_over_two} рядків створили понад 2 записи для одного класу/уроку; TV показує максимум 2"
        )
    if ignored_room_only:
        warnings.append(
            f"Проігноровано {ignored_room_only} службових клітинок, де був лише кабінет"
        )
    if recovered_subjects:
        warnings.append(
            f"Відновлено предмет для {recovered_subjects} групових рядків із візуально об’єднаних клітинок"
        )

    payload = {
        "schemaVersion": 1,
        "source": filename or path.name,
        "bellSchedule": bell_schedule,
        "days": days,
    }

    samples: list[dict[str, Any]] = []
    for day in expected_days:
        for class_name in CLASS_ORDER:
            for lesson, entries in sorted(
                days[day][class_name].items(), key=lambda x: int(x[0])
            ):
                if entries:
                    samples.append(
                        {
                            "day": day,
                            "class": class_name,
                            "lesson": int(lesson),
                            "entries": entries[:2],
                        }
                    )
                if len(samples) >= 18:
                    break
            if len(samples) >= 18:
                break
        if len(samples) >= 18:
            break

    preview = {
        "file_name": filename or path.name,
        "title": title,
        "sheet": ws.title,
        "suggested_target": suggested_target,
        "classes": sorted(
            source_classes,
            key=lambda x: CLASS_ORDER.index(x) if x in CLASS_ORDER else 99,
        ),
        "days": expected_days,
        "entry_count": entry_count,
        "occupied_lessons": occupied_lessons,
        "warnings": warnings[:80],
        "errors": errors[:80],
        "samples": samples,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    return payload, preview


def _cleanup_staging(max_age_seconds: int = 86400) -> None:
    STAGE_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - max_age_seconds
    for p in STAGE_DIR.glob("*"):
        try:
            if p.stat().st_mtime < cutoff:
                if p.is_dir():
                    shutil.rmtree(p)
                else:
                    p.unlink()
        except OSError:
            pass


def preview_upload(filename: str, data_b64: str) -> dict[str, Any]:
    _cleanup_staging()
    filename = Path(str(filename or "schedule.xlsx")).name
    if not filename.lower().endswith(".xlsx"):
        raise ValueError("Підтримуються тільки .xlsx")
    try:
        raw = base64.b64decode(str(data_b64 or ""), validate=True)
    except Exception as exc:
        raise ValueError("Некоректні дані XLSX") from exc
    if len(raw) < 100 or len(raw) > 8 * 1024 * 1024:
        raise ValueError("XLSX має бути від 100 B до 8 MB")
    if not raw.startswith(b"PK"):
        raise ValueError("Файл не є XLSX/ZIP")

    token = uuid.uuid4().hex
    stage = STAGE_DIR / token
    stage.mkdir(parents=True, exist_ok=False)
    xlsx = stage / "source.xlsx"
    xlsx.write_bytes(raw)
    payload, preview = parse_xlsx(xlsx, filename)
    (stage / "schedule.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (stage / "meta.json").write_text(
        json.dumps(
            {"filename": filename, "created_at": int(time.time()), "preview": preview},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"ok": not bool(preview["errors"]), "token": token, "preview": preview}


def get_preview(token: str) -> dict[str, Any]:
    token = str(token or "").strip()
    if not re.fullmatch(r"[0-9a-f]{32}", token):
        raise ValueError("Некоректний import token")
    meta = STAGE_DIR / token / "meta.json"
    if not meta.is_file():
        raise FileNotFoundError("Preview імпорту не знайдено або застарів")
    return json.loads(meta.read_text(encoding="utf-8"))


def apply_import(token: str, target: str, keep_count: int = 14) -> dict[str, Any]:
    target = str(target or "").strip()
    if target not in TARGETS:
        raise ValueError("Невідома ціль імпорту")
    meta = get_preview(token)
    preview = meta.get("preview", {})
    if preview.get("errors"):
        raise ValueError("Імпорт має помилки; застосування заблоковано")

    stage = STAGE_DIR / token
    schedule_path = stage / "schedule.json"
    source_path = stage / "source.xlsx"
    if not schedule_path.is_file() or not source_path.is_file():
        raise FileNotFoundError("Файли preview не знайдені")

    schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
    if not isinstance(schedule, dict) or not isinstance(schedule.get("days"), dict):
        raise ValueError("Некоректний schedule preview")

    backup = create_backup("pre-xlsx-import", keep_count)
    filename = TARGETS[target]
    raw = json.dumps(schedule, ensure_ascii=False, indent=2).encode("utf-8")

    written = []
    for folder in ("default", "current"):
        path = DATA / folder / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.import")
        tmp.write_bytes(raw)
        os.replace(tmp, path)
        written.append(str(path.relative_to(ROOT)))

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe_name = re.sub(
        r"[^A-Za-zА-Яа-яІіЇїЄєҐґ0-9._-]+",
        "_",
        str(meta.get("filename") or "schedule.xlsx"),
    )[:120]
    history = HISTORY_DIR / f"{stamp}-{target}-{safe_name}"
    shutil.copy2(source_path, history)

    digest = hashlib.sha256(raw).hexdigest()
    shutil.rmtree(stage, ignore_errors=True)
    return {
        "ok": True,
        "message": "XLSX застосовано",
        "target": target,
        "file": filename,
        "written": written,
        "entry_count": int(preview.get("entry_count") or 0),
        "sha256": digest,
        "backup": backup,
        "source_saved_as": str(history.relative_to(ROOT)),
    }
