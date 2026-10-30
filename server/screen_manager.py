from __future__ import annotations

import json
import os
import re
import threading
import time
import hashlib
import hmac
import secrets
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PATH = DATA / "screens.json"
_LOCK = threading.RLock()
_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,48}$")
_ALLOWED_PROFILES = {"schedule", "info", "shelter", "auto"}
_CACHE: dict[str, Any] | None = None
_LAST_FLUSH = 0.0
_FLUSH_INTERVAL = 60.0


def _atomic_write(payload: dict[str, Any]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(".json.tmp")
    descriptor = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(payload, output, ensure_ascii=False, indent=2)
    os.replace(tmp, PATH)
    PATH.chmod(0o600)


def pair_screen(screen_id: str, token: str = "") -> str:
    sid = _clean_id(screen_id)
    token = token or secrets.token_urlsafe(32)
    with _LOCK:
        screen = next((x for x in _data()["screens"] if x.get("id") == sid), None)
        if screen is None:
            if len(_data()["screens"]) >= 64:
                raise ValueError("Досягнуто ліміт 64 екрани")
            save_screen({"id": sid})
            screen = next(x for x in _data()["screens"] if x.get("id") == sid)
        screen["device_token_hash"] = hashlib.sha256(token.encode()).hexdigest()
        _flush(force=True)
    return token


def authenticate_screen(screen_id: str, token: str) -> bool:
    if not token:
        return False
    sid = _clean_id(screen_id)
    with _LOCK:
        screen = next((x for x in _data()["screens"] if x.get("id") == sid), {})
        expected = str(screen.get("device_token_hash", ""))
        return bool(expected) and hmac.compare_digest(
            expected, hashlib.sha256(token.encode()).hexdigest()
        )


def _load_disk() -> dict[str, Any]:
    try:
        obj = json.loads(PATH.read_text(encoding="utf-8"))
        if isinstance(obj, dict) and isinstance(obj.get("screens"), list):
            return obj
    except Exception:
        pass
    return {"screens": []}


def _data() -> dict[str, Any]:
    global _CACHE
    if _CACHE is None:
        _CACHE = _load_disk()
    return _CACHE


def _flush(force: bool = False) -> None:
    global _LAST_FLUSH
    now = time.monotonic()
    if force or now - _LAST_FLUSH >= _FLUSH_INTERVAL:
        _atomic_write(_data())
        _LAST_FLUSH = now


def _clean_id(value: Any) -> str:
    value = str(value or "").strip()
    if not _ID_RE.fullmatch(value):
        raise ValueError(
            "screen id: дозволено A-Z, a-z, 0-9, '.', '_' і '-' (1–48 символів)"
        )
    return value


def _clean_text(value: Any, limit: int = 120) -> str:
    return " ".join(str(value or "").replace("\x00", "").split())[:limit]


def _normalize_profile(value: Any) -> str:
    profile = str(value or "schedule").strip().lower()
    return profile if profile in _ALLOWED_PROFILES else "schedule"


def heartbeat(
    screen_id: str,
    *,
    name: str = "",
    profile: str = "",
    version: str = "",
    ip: str = "",
    user_agent: str = "",
    music_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sid = _clean_id(screen_id)
    now = int(time.time())
    with _LOCK:
        data = _data()
        items = data["screens"]
        screen = next(
            (x for x in items if isinstance(x, dict) and x.get("id") == sid), None
        )
        created = screen is None
        if screen is None:
            if len(items) >= 64:
                raise ValueError("Досягнуто ліміт 64 екрани")
            screen = {
                "id": sid,
                "name": _clean_text(name, 80) or sid,
                "profile": _normalize_profile(profile),
                "enabled": True,
                "created_at": now,
                "pending_command": "",
                "pending_command_payload": {},
                "command_id": 0,
                "last_command": "",
                "last_command_at": 0,
            }
            items.append(screen)
        else:
            if name and screen.get("name") in ("", sid):
                screen["name"] = _clean_text(name, 80) or sid
            if profile and not screen.get("profile"):
                screen["profile"] = _normalize_profile(profile)

        screen["last_seen"] = now
        screen["version"] = _clean_text(version, 40)
        screen["ip"] = _clean_text(ip, 64)
        screen["user_agent"] = _clean_text(user_agent, 220)
        if isinstance(music_status, dict):
            screen["music_status"] = {
                "state": _clean_text(music_status.get("state"), 30),
                "track_id": _clean_text(music_status.get("track_id"), 80),
                "title": _clean_text(music_status.get("title"), 160),
                "artist": _clean_text(music_status.get("artist"), 160),
                "playlist": _clean_text(music_status.get("playlist"), 30),
                "volume": music_status.get("volume", 0),
                "test_remaining": max(
                    0, min(30, int(music_status.get("test_remaining", 0) or 0))
                ),
                "updated_at": now,
            }
        data["screens"] = items

        # Heartbeats are frequent; flush at most once per minute to protect the SD card.
        _flush(force=created)

        command = str(screen.get("pending_command") or "")
        command_payload = (
            screen.get("pending_command_payload")
            if isinstance(screen.get("pending_command_payload"), dict)
            else {}
        )
        command_id = int(screen.get("command_id") or 0)
        return {
            "id": sid,
            "name": screen.get("name") or sid,
            "profile": screen.get("profile") or "schedule",
            "enabled": screen.get("enabled", True) is not False,
            "building": screen.get("building", ""),
            "floor": screen.get("floor", ""),
            "zone": screen.get("zone", ""),
            "music_status": screen.get("music_status", {}),
            "command": command,
            "command_payload": command_payload,
            "command_id": command_id,
        }


def acknowledge(screen_id: str, command_id: int) -> bool:
    sid = _clean_id(screen_id)
    with _LOCK:
        data = _data()
        changed = False
        for screen in data["screens"]:
            if not isinstance(screen, dict) or screen.get("id") != sid:
                continue
            if int(screen.get("command_id") or 0) == int(command_id or 0):
                screen["last_command"] = str(screen.get("pending_command") or "")
                screen["last_command_at"] = int(time.time())
                screen["pending_command"] = ""
                screen["pending_command_payload"] = {}
                changed = True
            break
        if changed:
            _flush(force=True)
        return changed


def list_screens(offline_seconds: int = 60) -> list[dict[str, Any]]:
    now = int(time.time())
    offline_seconds = max(15, min(3600, int(offline_seconds or 60)))
    with _LOCK:
        items = [
            {k: v for k, v in x.items() if k != "device_token_hash"}
            for x in _data()["screens"]
            if isinstance(x, dict)
        ]
    for x in items:
        last = int(x.get("last_seen") or 0)
        x["online"] = bool(
            last
            and now - last <= offline_seconds
            and x.get("enabled", True) is not False
        )
        x["age_seconds"] = max(0, now - last) if last else None
    return sorted(
        items,
        key=lambda x: (
            not x.get("online", False),
            str(x.get("name") or x.get("id") or ""),
        ),
    )


def save_screen(item: dict[str, Any]) -> dict[str, Any]:
    sid = _clean_id(item.get("id"))
    with _LOCK:
        data = _data()
        screen = next(
            (x for x in data["screens"] if isinstance(x, dict) and x.get("id") == sid),
            None,
        )
        if screen is None:
            screen = {
                "id": sid,
                "created_at": int(time.time()),
                "last_seen": 0,
                "version": "",
                "ip": "",
                "user_agent": "",
                "pending_command": "",
                "pending_command_payload": {},
                "command_id": 0,
                "last_command": "",
                "last_command_at": 0,
            }
            data["screens"].append(screen)

        screen["name"] = _clean_text(item.get("name"), 80) or sid
        screen["profile"] = _normalize_profile(item.get("profile"))
        screen["enabled"] = item.get("enabled", True) is not False
        screen["building"] = _clean_text(item.get("building"), 100)
        screen["floor"] = _clean_text(item.get("floor"), 40)
        screen["zone"] = _clean_text(item.get("zone"), 100)
        _flush(force=True)
        return {k: v for k, v in screen.items() if k != "device_token_hash"}


def queue_command(
    screen_id: str, command: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    sid = _clean_id(screen_id)
    command = str(command or "").strip().lower()
    if command not in {
        "reload",
        "restart",
        "wake",
        "music-play",
        "music-pause",
        "music-next",
        "music-stop",
        "music-test",
    }:
        raise ValueError("Невідома команда екрана")

    safe_payload: dict[str, Any] = {}
    if isinstance(payload, dict):
        # Command payload is intentionally tiny and text-only so screens.json
        # never becomes a general-purpose data transport.
        for key, limit in {
            "track_id": 80,
            "title": 160,
            "artist": 160,
            "url": 500,
            "playlist": 30,
        }.items():
            if key in payload:
                safe_payload[key] = _clean_text(payload.get(key), limit)
        if "duration" in payload:
            try:
                safe_payload["duration"] = max(
                    1, min(30, int(payload.get("duration") or 15))
                )
            except Exception:
                safe_payload["duration"] = 15
        if "volume" in payload:
            try:
                safe_payload["volume"] = max(
                    0.0, min(1.0, float(payload.get("volume") or 0))
                )
            except Exception:
                safe_payload["volume"] = 0.0

    with _LOCK:
        data = _data()
        screen = next(
            (x for x in data["screens"] if isinstance(x, dict) and x.get("id") == sid),
            None,
        )
        if screen is None:
            raise FileNotFoundError("Екран не знайдено")
        screen["command_id"] = int(screen.get("command_id") or 0) + 1
        screen["pending_command"] = command
        screen["pending_command_payload"] = safe_payload
        screen["command_queued_at"] = int(time.time())
        _flush(force=True)
        return {
            "id": sid,
            "command": command,
            "command_payload": safe_payload,
            "command_id": screen["command_id"],
        }


def delete_screen(screen_id: str) -> bool:
    sid = _clean_id(screen_id)
    with _LOCK:
        data = _data()
        before = len(data["screens"])
        data["screens"] = [
            x
            for x in data["screens"]
            if not (isinstance(x, dict) and x.get("id") == sid)
        ]
        if len(data["screens"]) != before:
            _flush(force=True)
            return True
        return False


def reload_from_disk() -> None:
    global _CACHE, _LAST_FLUSH
    with _LOCK:
        _CACHE = _load_disk()
        _LAST_FLUSH = time.monotonic()
