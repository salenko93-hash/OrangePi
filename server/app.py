from __future__ import annotations
from media_io import save_stream, send_media

import json
import re
import mimetypes
import os
import signal
import sys
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PUBLIC = ROOT / "public"
sys.path.insert(0, str(HERE))

from backup_manager import create_backup, delete_backup, list_backups, restore_backup
from bell_store import load_bells, save_bells
from calendar_store import (
    delete as delete_calendar,
    load_override as load_calendar,
    upsert as upsert_calendar,
)
from config_store import ConfigStore, RuntimeStore
from security import resolve_role, allowed
from auth_sessions import SESSIONS, COOKIE, TTL
from http_security import SecureHTTPMixin, BoundedHTTPServer
from runtime_data import initialize_runtime_data
from http_responses import ResponseMixin
from version import VERSION
from content_store import (
    delete as delete_content,
    load_control,
    upsert as upsert_content,
)
from engine import Engine
from event_log import clear_events, read_events, write_event
from mobile_api import build_mobile_schedule
from schedule_engine import CLASS_ORDER
from ota_manager import apply_package, check_manifest, current_version
from qr_maker import make_svg as make_qr_svg
from screen_manager import (
    acknowledge as screen_acknowledge,
    delete_screen,
    heartbeat as screen_heartbeat,
    list_screens,
    queue_command,
    save_screen,
    reload_from_disk as reload_screens,
    pair_screen,
    authenticate_screen,
)
from system_monitor import system_status
from smart_ops import (
    active_events,
    after_school_slides,
    slideshow_url,
    MEDIA_DIR,
    audio_current,
    campus_stats,
    delete as smart_delete,
    directory as smart_directory,
    free_rooms,
    health_alerts,
    load_ops,
    music_state,
    notifications_for,
    notify_from_announcement,
    notify_from_substitution,
    public_campus,
    room_schedule,
    save_media_upload,
    signage_current,
    teacher_schedule,
    upsert as smart_upsert,
)
from telegram_monitor import TelegramMonitor
from xlsx_importer import (
    apply_import as apply_xlsx_import,
    preview_upload as preview_xlsx_upload,
)

initialize_runtime_data(ROOT)

CONFIG = ConfigStore()
RUNTIME = RuntimeStore()
ENGINE = Engine(CONFIG, RUNTIME)


def _restart_self(delay: float = 1.2) -> None:
    def worker():
        time.sleep(delay)
        os._exit(0)

    threading.Thread(target=worker, daemon=True).start()


TELEGRAM = TelegramMonitor(
    CONFIG,
    state_cb=ENGINE.get_state,
    sync_cb=lambda: ENGINE.sync_now(background=False),
    restart_cb=lambda: _restart_self(0.5),
    version_cb=current_version,
)


class Handler(SecureHTTPMixin, ResponseMixin, BaseHTTPRequestHandler):
    server_version = f"LyceumTV/{VERSION}"

    def log_message(self, fmt, *args):
        sys.stdout.write("%s - %s\n" % (self.log_date_time_string(), fmt % args))
        sys.stdout.flush()

    def _authorized(self) -> bool:
        return self._role() == "admin"

    def _role(self) -> str:
        config = CONFIG.load()
        role = resolve_role(
            config,
            self.headers.get("X-Admin-Key", ""),
            self.headers.get("X-Role-Key", ""),
        )
        return role or SESSIONS.resolve(self.headers.get("Cookie", ""), config)

    def _role_allowed(self, *roles: str) -> bool:
        return allowed(self._role(), *roles)

    def _read_json(self, max_bytes: int = 12 * 1024 * 1024):
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except Exception:
            n = 0
        if n <= 0:
            return {}
        if n > max_bytes:
            raise ValueError("Запит завеликий")
        raw = self.rfile.read(n)

        def reject_constant(value):
            raise ValueError("JSON не може містити NaN або Infinity")

        return json.loads(raw.decode("utf-8"), parse_constant=reject_constant)

    def _update_status(self):
        from update_transaction import read_state

        try:
            pending = read_state(ROOT)
            last_path = ROOT / "data/last_update.json"
            last = json.loads(last_path.read_text()) if last_path.exists() else None
            return {"pending": pending, "last": last}
        except (ValueError, OSError) as error:
            return {"error": str(error)}

    def _dashboard(self):
        cfg = CONFIG.public()
        screens = list_screens(int(cfg.get("screen_offline_seconds", 60) or 60))
        return {
            "ok": True,
            "config": cfg,
            "state": ENGINE.get_state(),
            "system": system_status(),
            "control": load_control(),
            "calendar": load_calendar(),
            "bells": load_bells(),
            "backups": list_backups(),
            "logs": read_events(160),
            "screens": screens,
            "ota": {
                "current": current_version(),
                "configured": bool(str(cfg.get("ota_manifest_url", "")).strip()),
            },
            "smart_campus": {
                "mobile_url": "/mobile/",
                "screens_online": sum(1 for x in screens if x.get("online")),
                "screens_total": len(screens),
                "telegram_configured": bool(
                    cfg.get("telegram_bot_token_set") and cfg.get("telegram_chat_id")
                ),
            },
            "update": self._update_status(),
            "telegram": TELEGRAM.status(),
            "operations": {
                "stats": campus_stats(cfg),
                "notifications": len(load_ops().get("notifications", [])),
                "media": len(load_ops().get("media", [])),
                "signage_rules": len(load_ops().get("signage_rules", [])),
                "audio_events": len(load_ops().get("audio_events", [])),
                "music_tracks": len(load_ops().get("music_tracks", [])),
                "music": music_state(CONFIG.load(), ENGINE.get_state()),
                "health_alerts": health_alerts(
                    system_status(), screens, ENGINE.get_state(), CONFIG.load()
                ),
            },
        }

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/api/health":
            return self._send_json(
                200, {"ok": True, "service": "LyceumTV", "version": VERSION}
            )

        if path == "/api/auth/session":
            return self._send_json(200, {"ok": True, "role": self._role()})

        if path == "/api/screen/local-token":
            # nginx always supplies forwarded headers; remote clients cannot
            # obtain this bootstrap even though the proxy connects from localhost.
            if (
                not self.direct_loopback()
                or self.headers.get("Sec-Fetch-Site") == "cross-site"
            ):
                return self._send_json(
                    403, {"ok": False, "error": "Лише локальний kiosk"}
                )
            config = CONFIG.load()
            sid = str((query.get("id") or [""])[0])
            if sid != str(config.get("main_screen_id", "main-hall")):
                return self._send_json(
                    403, {"ok": False, "error": "Лише головний kiosk"}
                )
            token = pair_screen(sid, str(config.get("local_screen_token", "")))
            return self._send_json(200, {"ok": True, "token": token})

        if path == "/api/state":
            return self._send_json(200, ENGINE.get_state())

        if path == "/api/mobile/schedule":
            cfg = CONFIG.load()
            if not bool(cfg.get("mobile_enabled", True)):
                return self._send_json(
                    403, {"ok": False, "error": "Mobile schedule вимкнено"}
                )
            class_name = str((query.get("class") or [""])[0])
            day_text = str((query.get("date") or [""])[0])
            try:
                day = date.fromisoformat(day_text) if day_text else date.today()
                result = build_mobile_schedule(class_name, day, cfg)
                return self._send_json(200, result)
            except Exception as exc:
                return self._send_json(400, {"ok": False, "error": str(exc)})

        if path == "/api/qr.svg":
            text = str((query.get("text") or [""])[0])
            try:
                raw = make_qr_svg(text)
                return self._send_raw(
                    200, raw, "image/svg+xml; charset=utf-8", "public, max-age=300"
                )
            except Exception as exc:
                return self._send_json(400, {"ok": False, "error": str(exc)})

        if path == "/api/notifications":
            cfg = CONFIG.load()
            if not bool(cfg.get("notifications_enabled", True)):
                return self._send_json(200, {"ok": True, "items": []})
            class_name = str((query.get("class") or [""])[0]).strip()
            teacher = str((query.get("teacher") or [""])[0]).strip()
            screen = str((query.get("screen") or [""])[0]).strip()
            try:
                after = int((query.get("after") or ["0"])[0] or 0)
            except Exception:
                after = 0
            return self._send_json(
                200,
                {
                    "ok": True,
                    "items": notifications_for(
                        class_name=class_name,
                        teacher=teacher,
                        screen=screen,
                        after=after,
                    ),
                },
            )

        if path == "/api/campus":
            cfg = CONFIG.load()
            if not bool(cfg.get("public_service_enabled", True)):
                return self._send_json(
                    403, {"ok": False, "error": "Campus service вимкнено"}
                )
            return self._send_json(200, public_campus(cfg))

        if path == "/api/public/export":
            cfg = CONFIG.load()
            if not bool(cfg.get("public_service_enabled", True)):
                return self._send_json(
                    403, {"ok": False, "error": "Public export вимкнено"}
                )
            payload = public_campus(cfg)
            payload["stats"] = campus_stats(cfg)
            payload["generated_at"] = int(time.time())
            return self._send_json(200, payload)

        if path == "/api/slideshow":
            payload = after_school_slides()
            cfg = CONFIG.load()
            payload["title"] = " ".join(
                str(cfg.get("slideshow_title") or "ЖИТТЯ ЛІЦЕЮ").split()
            )[:120]
            payload["music"] = {
                "url": slideshow_url(cfg.get("slideshow_music_url")),
                "volume": max(0, min(100, int(cfg.get("slideshow_volume_percent", 35))))
                / 100,
                "screen_id": str(cfg.get("slideshow_audio_screen_id") or "main-hall"),
            }
            return self._send_json(200, payload)

        if path == "/api/signage/current":
            screen_id = (
                str((query.get("screen") or ["main-hall"])[0]).strip() or "main-hall"
            )
            return self._send_json(200, signage_current(CONFIG.load(), screen_id))

        if path == "/api/audio/current":
            return self._send_json(200, audio_current(CONFIG.load()))

        if path == "/api/music/state":
            cfg = CONFIG.load()
            return self._send_json(200, music_state(cfg, ENGINE.get_state()))

        if path == "/api/teacher/directory":
            if not self._role_allowed("teacher", "dispatcher"):
                return self._send_json(
                    401, {"ok": False, "error": "Потрібен Teacher/Dispatcher key"}
                )
            return self._send_json(200, {"ok": True, **smart_directory()})

        if path == "/api/teacher/schedule":
            if not self._role_allowed("teacher", "dispatcher"):
                return self._send_json(
                    401, {"ok": False, "error": "Потрібен Teacher/Dispatcher key"}
                )
            teacher = str((query.get("teacher") or [""])[0]).strip()
            day_text = str((query.get("date") or [""])[0]).strip()
            try:
                day = date.fromisoformat(day_text) if day_text else date.today()
                return self._send_json(
                    200, teacher_schedule(teacher, day, CONFIG.load())
                )
            except Exception as exc:
                return self._send_json(400, {"ok": False, "error": str(exc)})

        if path == "/api/ops/dashboard":
            if not self._role_allowed("dispatcher"):
                return self._send_json(
                    401, {"ok": False, "error": "Потрібен Dispatcher/Admin key"}
                )
            cfg = CONFIG.load()
            screens = list_screens(int(cfg.get("screen_offline_seconds", 60) or 60))
            sysinfo = system_status()
            state = ENGINE.get_state()
            return self._send_json(
                200,
                {
                    "ok": True,
                    "role": self._role(),
                    "state": state,
                    "system": sysinfo,
                    "screens": screens,
                    "smart": load_ops(),
                    "content": load_control(),
                    "events": active_events(),
                    "stats": campus_stats(cfg),
                    "health_alerts": health_alerts(sysinfo, screens, state, cfg),
                    "logs": read_events(120),
                    "directory": smart_directory(),
                    "config_public": CONFIG.public(),
                    "music": music_state(cfg, state),
                },
            )

        if path == "/api/ops/free-rooms":
            if not self._role_allowed("dispatcher"):
                return self._send_json(
                    401, {"ok": False, "error": "Потрібен Dispatcher/Admin key"}
                )
            day_text = str((query.get("date") or [""])[0]).strip()
            lesson_text = str((query.get("lesson") or ["1"])[0]).strip()
            try:
                day = date.fromisoformat(day_text) if day_text else date.today()
                return self._send_json(
                    200, free_rooms(day, int(lesson_text), CONFIG.load())
                )
            except Exception as exc:
                return self._send_json(400, {"ok": False, "error": str(exc)})

        if path == "/api/ops/room-schedule":
            if not self._role_allowed("dispatcher"):
                return self._send_json(
                    401, {"ok": False, "error": "Потрібен Dispatcher/Admin key"}
                )
            day_text = str((query.get("date") or [""])[0]).strip()
            room = str((query.get("room") or [""])[0]).strip()
            try:
                day = date.fromisoformat(day_text) if day_text else date.today()
                return self._send_json(200, room_schedule(room, day, CONFIG.load()))
            except Exception as exc:
                return self._send_json(400, {"ok": False, "error": str(exc)})

        if path == "/api/admin/config":
            if not self._authorized():
                return self._send_json(
                    401, {"ok": False, "error": "Невірний admin key"}
                )
            return self._send_json(
                200,
                {"ok": True, "config": CONFIG.public(), "state": ENGINE.get_state()},
            )

        if path == "/api/admin/dashboard":
            if not self._authorized():
                return self._send_json(
                    401, {"ok": False, "error": "Невірний admin key"}
                )
            return self._send_json(200, self._dashboard())

        if path in {"/demo", "/demo/"}:
            path = "/demo.html"
        elif path == "/slideshow-preview":
            path = "/slideshow-preview.html"
        elif path == "/admin":
            path = "/admin.html"
        elif path == "/teacher":
            path = "/teacher.html"
        elif path == "/ops":
            path = "/ops.html"
        elif path in {"/campus", "/campus/"}:
            path = "/campus/index.html"
        elif path == "/signage":
            path = "/signage.html"
        elif path in {"/mobile", "/mobile/"}:
            path = "/mobile/index.html"
        elif path == "/":
            path = "/index.html"
        return self._serve_static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/auth/login":
            if not (self.is_secure() or self.direct_loopback()):
                return self._send_json(
                    403, {"ok": False, "error": "Для входу потрібен HTTPS"}
                )
            try:
                body = self._read_json(4096)
                config = CONFIG.load()
                role = resolve_role(config, "", str(body.get("key", "")))
                if not role:
                    return self._send_json(401, {"ok": False, "error": "Невірний ключ"})
                SESSIONS.revoke(self.headers.get("Cookie", ""))
                token = SESSIONS.create(role, config)
                secure = "; Secure" if self.is_secure() else ""
                self.response_cookie = f"{COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={TTL}{secure}"
                return self._send_json(200, {"ok": True, "role": role})
            except (ValueError, TypeError, AttributeError):
                return self._send_json(
                    400, {"ok": False, "error": "Некоректний запит входу"}
                )

        if path == "/api/auth/logout":
            SESSIONS.revoke(self.headers.get("Cookie", ""))
            self.response_cookie = (
                f"{COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"
                + ("; Secure" if self.is_secure() else "")
            )
            return self._send_json(200, {"ok": True})

        if path == "/api/ops/media/upload-file":
            self.close_connection = True
            if not self._role_allowed("dispatcher"):
                return self._send_json(
                    401, {"ok": False, "error": "Потрібен Dispatcher/Admin key"}
                )
            timeout = self.connection.gettimeout()
            try:
                self.connection.settimeout(120)
                name = (parse_qs(parsed.query).get("name") or [""])[0]
                length = int(self.headers.get("Content-Length", "0"))
                saved = save_stream(MEDIA_DIR, name, self.rfile, length)
                write_event(
                    "ops.media.upload",
                    "Медіафайл завантажено",
                    saved,
                    actor=self._role(),
                )
                return self._send_json(200, saved)
            except (ValueError, OSError) as exc:
                return self._send_json(400, {"ok": False, "error": str(exc)})
            finally:
                self.connection.settimeout(timeout)

        if path == "/api/ops/media/cleanup":
            if not self._role_allowed("dispatcher"):
                return self._send_json(
                    401, {"ok": False, "error": "Потрібен Dispatcher/Admin key"}
                )
            try:
                from media_library import cleanup

                body = self._read_json(4096)
                return self._send_json(
                    200, cleanup(ROOT, dry_run=body.get("dry_run", True) is not False)
                )
            except (ValueError, OSError) as error:
                return self._send_json(400, {"ok": False, "error": str(error)})

        if path == "/api/ops/slideshow/settings":
            if not self._role_allowed("dispatcher"):
                return self._send_json(
                    401, {"ok": False, "error": "Потрібен Dispatcher/Admin key"}
                )
            try:
                body = self._read_json(8192)
                patch = {}
                if "slideshow_music_url" in body:
                    raw = str(body["slideshow_music_url"] or "").strip()
                    if raw and not slideshow_url(raw):
                        raise ValueError("Вкажіть медіафайл або HTTPS URL")
                    patch["slideshow_music_url"] = raw
                if "slideshow_volume_percent" in body:
                    patch["slideshow_volume_percent"] = max(
                        0, min(100, int(body["slideshow_volume_percent"]))
                    )
                if "slideshow_audio_screen_id" in body:
                    screen = str(body["slideshow_audio_screen_id"]).strip()
                    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", screen):
                        raise ValueError("Некоректний ID екрана")
                    patch["slideshow_audio_screen_id"] = screen
                CONFIG.save(patch)
                return self._send_json(
                    200, {"ok": True, "config_public": CONFIG.public()}
                )
            except (ValueError, TypeError) as exc:
                return self._send_json(400, {"ok": False, "error": str(exc)})

        # Public Smart Campus screen heartbeat. The identifier is validated and
        # the response only contains the command queued for that same screen.
        if path == "/api/screen/heartbeat":
            try:
                body = self._read_json(128 * 1024)
                if not authenticate_screen(
                    str(body.get("id", "")), self.headers.get("X-Device-Token", "")
                ):
                    return self._send_json(
                        401,
                        {
                            "ok": False,
                            "error": "Екран не підключено. Потрібен токен пристрою",
                        },
                    )
                item = screen_heartbeat(
                    str(body.get("id", "")),
                    name=str(body.get("name", "")),
                    profile=str(body.get("profile", "")),
                    version=str(body.get("version", "")),
                    ip=str(self.client_address[0] if self.client_address else ""),
                    user_agent=str(self.headers.get("User-Agent", "")),
                    music_status=body.get("music_status")
                    if isinstance(body.get("music_status"), dict)
                    else None,
                )
                return self._send_json(200, {"ok": True, "screen": item})
            except Exception as exc:
                return self._send_json(400, {"ok": False, "error": str(exc)})

        if path == "/api/screen/ack":
            try:
                body = self._read_json(64 * 1024)
                if not authenticate_screen(
                    str(body.get("id", "")), self.headers.get("X-Device-Token", "")
                ):
                    return self._send_json(
                        401, {"ok": False, "error": "Потрібен токен пристрою"}
                    )
                changed = screen_acknowledge(
                    str(body.get("id", "")), int(body.get("command_id", 0) or 0)
                )
                return self._send_json(200, {"ok": True, "acknowledged": changed})
            except Exception as exc:
                return self._send_json(400, {"ok": False, "error": str(exc)})

        if path == "/api/ops/duty/settings":
            if not self._role_allowed("dispatcher"):
                return self._send_json(
                    401, {"ok": False, "error": "Потрібен Dispatcher/Admin key"}
                )
            try:
                body = self._read_json()
                incoming = body.get("config", body) if isinstance(body, dict) else {}
                if not isinstance(incoming, dict):
                    incoming = {}

                patch = {}
                if "duty_class_enabled" in incoming:
                    patch["duty_class_enabled"] = bool(
                        incoming.get("duty_class_enabled")
                    )
                if "duty_skip_full_holiday_weeks" in incoming:
                    patch["duty_skip_full_holiday_weeks"] = bool(
                        incoming.get("duty_skip_full_holiday_weeks")
                    )

                start_date = str(
                    incoming.get("duty_rotation_start_date", "") or ""
                ).strip()
                if start_date:
                    date.fromisoformat(start_date)
                    patch["duty_rotation_start_date"] = start_date

                start_class = (
                    str(incoming.get("duty_rotation_start_class", "") or "")
                    .strip()
                    .upper()
                )
                if start_class:
                    if start_class not in CLASS_ORDER:
                        raise ValueError("Невідомий перший черговий клас")
                    patch["duty_rotation_start_class"] = start_class

                manual = (
                    str(incoming.get("duty_manual_class", "") or "").strip().upper()
                )
                if manual and manual not in CLASS_ORDER:
                    raise ValueError("Невідомий ручний черговий клас")
                patch["duty_manual_class"] = manual

                label = " ".join(
                    str(incoming.get("duty_class_label", "") or "").split()
                )[:40]
                if label:
                    patch["duty_class_label"] = label

                order_raw = incoming.get("duty_rotation_order")
                if isinstance(order_raw, str):
                    order_raw = [
                        x.strip().upper()
                        for x in order_raw.replace(";", ",").split(",")
                        if x.strip()
                    ]
                if isinstance(order_raw, list):
                    clean = []
                    for item in order_raw:
                        name = str(item or "").strip().upper()
                        if name in CLASS_ORDER and name not in clean:
                            clean.append(name)
                    if set(clean) != set(CLASS_ORDER) or len(clean) != len(CLASS_ORDER):
                        raise ValueError(
                            "Порядок чергування повинен містити всі 8 класів по одному разу"
                        )
                    patch["duty_rotation_order"] = clean

                saved = CONFIG.save(patch)
                state = ENGINE.get_state()
                write_event(
                    "duty.settings",
                    "Налаштування чергування класів збережено",
                    {"keys": sorted(patch), "duty": state.get("duty", {})},
                    actor=self._role(),
                )
                return self._send_json(
                    200,
                    {
                        "ok": True,
                        "config": CONFIG.public(),
                        "duty": state.get("duty", {}),
                        "message": "Чергування класів збережено",
                    },
                )
            except Exception as exc:
                return self._send_json(400, {"ok": False, "error": str(exc)})

        if path == "/api/ops/music/settings":
            if not self._role_allowed("dispatcher"):
                return self._send_json(
                    401, {"ok": False, "error": "Потрібен Dispatcher/Admin key"}
                )
            try:
                body = self._read_json()
                allowed = {
                    "music_enabled",
                    "music_breaks_enabled",
                    "music_after_school_enabled",
                    "music_after_school_until",
                    "music_volume_percent",
                    "music_shuffle",
                    "music_fade_seconds",
                    "music_break_fade_before_end_seconds",
                    "music_main_screen_id",
                }
                patch = {
                    k: v
                    for k, v in (
                        body.get("config", body) if isinstance(body, dict) else {}
                    ).items()
                    if k in allowed
                }
                saved = CONFIG.save(patch)
                write_event(
                    "music.settings",
                    "Налаштування Music Scheduler збережено",
                    {"keys": sorted(patch)},
                    actor=self._role(),
                )
                return self._send_json(
                    200,
                    {
                        "ok": True,
                        "config": CONFIG.public(),
                        "message": "Music Scheduler збережено",
                    },
                )
            except Exception as exc:
                return self._send_json(400, {"ok": False, "error": str(exc)})

        if path == "/api/ops/music/command":
            if not self._role_allowed("dispatcher"):
                return self._send_json(
                    401, {"ok": False, "error": "Потрібен Dispatcher/Admin key"}
                )
            try:
                body = self._read_json()
                command = str(body.get("command", "")).strip().lower()
                if command not in {
                    "music-play",
                    "music-pause",
                    "music-next",
                    "music-stop",
                    "music-test",
                }:
                    raise ValueError("Невідома музична команда")
                cfg_now = CONFIG.load()
                screen_id = str(
                    body.get("screen")
                    or cfg_now.get("music_main_screen_id")
                    or "main-hall"
                )
                payload = None

                if command == "music-test":
                    # First safety gate is server-side. The TV performs the same
                    # check again immediately before play, so a mode transition
                    # between API call and heartbeat cannot bypass safety.
                    state_now = ENGINE.get_state()
                    mode_now = str(state_now.get("mode") or "NORMAL")
                    if mode_now != "NORMAL":
                        return self._send_json(
                            409,
                            {
                                "ok": False,
                                "error": f"TV тест музики заблоковано: активний режим {mode_now}",
                                "mode": mode_now,
                            },
                        )
                    if audio_current(cfg_now).get("event"):
                        return self._send_json(
                            409,
                            {
                                "ok": False,
                                "error": "TV тест музики заблоковано: зараз активна системна аудіоподія",
                                "mode": mode_now,
                            },
                        )

                    tracks = [
                        x
                        for x in load_ops().get("music_tracks", [])
                        if isinstance(x, dict)
                        and x.get("active", True) is not False
                        and str(x.get("url") or "").strip()
                    ]
                    requested = str(body.get("track_id") or "").strip()
                    track = (
                        next(
                            (x for x in tracks if str(x.get("id") or "") == requested),
                            None,
                        )
                        if requested
                        else None
                    )
                    if track is None and tracks:
                        tracks.sort(
                            key=lambda x: (
                                int(x.get("order") or 100),
                                str(x.get("title") or "").lower(),
                            )
                        )
                        track = tracks[0]
                    if track is None:
                        raise ValueError("У плейлисті немає активних треків для тесту")

                    payload = {
                        "track_id": str(track.get("id") or ""),
                        "title": str(track.get("title") or "Музичний трек"),
                        "artist": str(track.get("artist") or ""),
                        "url": str(track.get("url") or ""),
                        "playlist": str(track.get("playlist") or "both"),
                        "duration": 15,
                        "volume": max(
                            0.0,
                            min(
                                1.0,
                                float(cfg_now.get("music_volume_percent", 35) or 35)
                                / 100.0,
                            ),
                        ),
                    }

                item = queue_command(screen_id, command, payload)
                write_event(
                    "music.test" if command == "music-test" else "music.command",
                    "Безпечний тест музики 15 с"
                    if command == "music-test"
                    else "Music Scheduler command",
                    item,
                    actor=self._role(),
                )
                return self._send_json(
                    200,
                    {
                        "ok": True,
                        "command": item,
                        "message": "TV тест 15 секунд надіслано"
                        if command == "music-test"
                        else "Команду надіслано",
                    },
                )
            except Exception as exc:
                return self._send_json(400, {"ok": False, "error": str(exc)})

        if path == "/api/ops/item":
            if not self._role_allowed("dispatcher"):
                return self._send_json(
                    401, {"ok": False, "error": "Потрібен Dispatcher/Admin key"}
                )
            try:
                body = self._read_json()
                kind = str(body.get("kind", "")).strip().lower()
                op = str(body.get("op", "save")).strip().lower()
                if op == "delete":
                    changed = smart_delete(kind, str(body.get("id", "")))
                    write_event(
                        f"ops.{kind}.delete",
                        f"Smart Operations: видалено {kind}",
                        {"id": body.get("id", "")},
                        actor=self._role(),
                    )
                    return self._send_json(
                        200,
                        {
                            "ok": True,
                            "message": "Видалено" if changed else "Не знайдено",
                        },
                    )
                item = smart_upsert(
                    kind, body.get("item", {}) if isinstance(body, dict) else {}
                )
                write_event(
                    f"ops.{kind}.save",
                    f"Smart Operations: збережено {kind}",
                    {"id": item.get("id", "")},
                    actor=self._role(),
                )
                return self._send_json(200, {"ok": True, "item": item})
            except Exception as exc:
                return self._send_json(400, {"ok": False, "error": str(exc)})

        if path == "/api/ops/media/upload":
            if not self._role_allowed("dispatcher"):
                return self._send_json(
                    401, {"ok": False, "error": "Потрібен Dispatcher/Admin key"}
                )
            try:
                body = self._read_json(48 * 1024 * 1024)
                saved = save_media_upload(
                    str(body.get("file_name", "media")),
                    str(body.get("data_base64", "")),
                )
                write_event(
                    "ops.media.upload",
                    "Медіафайл завантажено",
                    saved,
                    actor=self._role(),
                )
                return self._send_json(200, {"ok": True, **saved})
            except Exception as exc:
                return self._send_json(400, {"ok": False, "error": str(exc)})

        if path == "/api/ops/substitution":
            if not self._role_allowed("dispatcher"):
                return self._send_json(
                    401, {"ok": False, "error": "Потрібен Dispatcher/Admin key"}
                )
            try:
                body = self._read_json()
                op = str(body.get("op", "save")).strip().lower()
                if op == "delete":
                    changed = delete_content("substitution", str(body.get("id", "")))
                    write_event(
                        "substitution.delete",
                        "Заміна видалена через Operations",
                        {"id": body.get("id", "")},
                        actor=self._role(),
                    )
                    return self._send_json(
                        200,
                        {
                            "ok": True,
                            "message": "Видалено" if changed else "Не знайдено",
                        },
                    )
                item = upsert_content("substitution", body.get("item", {}))
                if CONFIG.load().get("auto_notify_substitutions", True):
                    notify_from_substitution(item)
                write_event(
                    "substitution.save",
                    "Заміна збережена через Operations",
                    {"id": item.get("id", "")},
                    actor=self._role(),
                )
                if CONFIG.load().get("telegram_chat_id"):
                    TELEGRAM.notify(
                        f"🔄 Заміна: {item.get('date', '')} {item.get('class', '')} • {item.get('lesson', '')} урок"
                    )
                return self._send_json(200, {"ok": True, "item": item})
            except Exception as exc:
                return self._send_json(400, {"ok": False, "error": str(exc)})

        if not path.startswith("/api/admin/"):
            return self._send_json(404, {"ok": False, "error": "Not found"})
        if not self._authorized():
            return self._send_json(401, {"ok": False, "error": "Невірний admin key"})

        try:
            body = self._read_json()

            if path == "/api/admin/config":
                patch = body.get("config", body) if isinstance(body, dict) else {}
                if not isinstance(patch, dict):
                    raise ValueError("config must be object")
                if not str(patch.get("alerts_token", "")).strip():
                    patch.pop("alerts_token", None)
                if not str(patch.get("telegram_bot_token", "")).strip():
                    patch.pop("telegram_bot_token", None)
                for secret_key in (
                    "dispatcher_key",
                    "teacher_key",
                    "cloud_mirror_token",
                ):
                    if not str(patch.get(secret_key, "")).strip():
                        patch.pop(secret_key, None)
                new_key = str(patch.get("admin_key", "")).strip()
                if not new_key:
                    patch.pop("admin_key", None)
                saved = CONFIG.save(patch)
                threading.Thread(
                    target=ENGINE.refresh_weather, args=(saved,), daemon=True
                ).start()
                write_event(
                    "config", "Налаштування Smart Campus збережено", actor="admin"
                )
                return self._send_json(
                    200,
                    {
                        "ok": True,
                        "message": "Налаштування збережено",
                        "config": CONFIG.public(),
                    },
                )

            if path == "/api/admin/item":
                kind = str(body.get("kind", "")).strip().lower()
                op = str(body.get("op", "save")).strip().lower()
                if op == "delete":
                    changed = delete_content(kind, str(body.get("id", "")))
                    write_event(
                        f"{kind}.delete",
                        f"Видалено: {kind}",
                        {"id": body.get("id", "")},
                        actor="admin",
                    )
                    return self._send_json(
                        200,
                        {
                            "ok": True,
                            "message": "Видалено" if changed else "Запис не знайдено",
                        },
                    )
                item = upsert_content(
                    kind, body.get("item", {}) if isinstance(body, dict) else {}
                )
                cfg_now = CONFIG.load()
                if kind == "substitution" and cfg_now.get(
                    "auto_notify_substitutions", True
                ):
                    notify_from_substitution(item)
                    if cfg_now.get("telegram_chat_id"):
                        TELEGRAM.notify(
                            f"🔄 Заміна: {item.get('date', '')} {item.get('class', '')} • {item.get('lesson', '')} урок"
                        )
                elif kind == "announcement" and cfg_now.get(
                    "auto_notify_announcements", True
                ):
                    notify_from_announcement(item)
                write_event(
                    f"{kind}.save",
                    f"Збережено: {kind}",
                    {"id": item.get("id", "")},
                    actor="admin",
                )
                return self._send_json(
                    200, {"ok": True, "message": "Збережено", "item": item}
                )

            if path == "/api/admin/calendar":
                kind = str(body.get("kind", "")).strip()
                op = str(body.get("op", "save")).strip().lower()
                if op == "delete":
                    changed = delete_calendar(kind, str(body.get("id", "")))
                    write_event(
                        "calendar.delete",
                        "Календар: запис видалено",
                        {"kind": kind, "id": body.get("id", "")},
                        actor="admin",
                    )
                    return self._send_json(
                        200,
                        {
                            "ok": True,
                            "message": "Видалено" if changed else "Запис не знайдено",
                        },
                    )
                item = upsert_calendar(kind, body.get("item", {}))
                write_event(
                    "calendar.save",
                    "Календар: запис збережено",
                    {"kind": kind, "id": item.get("id", "")},
                    actor="admin",
                )
                return self._send_json(
                    200, {"ok": True, "message": "Календар оновлено", "item": item}
                )

            if path == "/api/admin/bells":
                bells = save_bells(body.get("bells", []))
                write_event(
                    "bells.save",
                    "Розклад дзвінків оновлено",
                    {"count": len(bells)},
                    actor="admin",
                )
                return self._send_json(
                    200, {"ok": True, "message": "Дзвінки збережено", "bells": bells}
                )

            if path == "/api/admin/screen":
                op = str(body.get("op", "save")).strip().lower()
                if op == "pair":
                    sid = str(body.get("id", ""))
                    token = pair_screen(sid)
                    return self._send_json(200, {"ok": True, "id": sid, "token": token})
                if op == "save":
                    item = save_screen(
                        body.get("screen", {}) if isinstance(body, dict) else {}
                    )
                    write_event(
                        "screen.save",
                        "Профіль екрана збережено",
                        {"id": item.get("id")},
                        actor="admin",
                    )
                    return self._send_json(
                        200, {"ok": True, "message": "Екран збережено", "screen": item}
                    )
                if op == "delete":
                    changed = delete_screen(str(body.get("id", "")))
                    write_event(
                        "screen.delete",
                        "Екран видалено",
                        {"id": body.get("id", "")},
                        actor="admin",
                    )
                    return self._send_json(
                        200,
                        {
                            "ok": True,
                            "message": "Екран видалено"
                            if changed
                            else "Екран не знайдено",
                        },
                    )
                if op == "command":
                    item = queue_command(
                        str(body.get("id", "")), str(body.get("command", "reload"))
                    )
                    write_event(
                        "screen.command",
                        "Команду екрана поставлено в чергу",
                        item,
                        actor="admin",
                    )
                    return self._send_json(
                        200,
                        {"ok": True, "message": "Команду надіслано", "command": item},
                    )
                raise ValueError("Невідома операція екрана")

            if path == "/api/admin/xlsx/preview":
                file_name = str(body.get("file_name", "schedule.xlsx"))
                data_b64 = str(body.get("data_base64", ""))
                result = preview_xlsx_upload(file_name, data_b64)
                write_event(
                    "xlsx.preview",
                    "XLSX перевірено",
                    {
                        "file": file_name,
                        "entries": result.get("preview", {}).get("entry_count", 0),
                        "errors": len(result.get("preview", {}).get("errors", [])),
                    },
                    actor="admin",
                )
                return self._send_json(200, result)

            if path == "/api/admin/xlsx/apply":
                token = str(body.get("token", ""))
                target = str(body.get("target", ""))
                result = apply_xlsx_import(
                    token,
                    target,
                    int(CONFIG.load().get("backup_keep_count", 14) or 14),
                )
                cfg = CONFIG.load()
                pins = [str(x) for x in (cfg.get("pinned_local_schedules", []) or [])]
                if target != "schedule_denominator" and target not in pins:
                    pins.append(target)
                patch = {"pinned_local_schedules": pins}
                if target == "schedule_denominator":
                    patch["pin_local_denominator"] = True
                CONFIG.save(patch)
                result["pinned_local"] = True
                write_event(
                    "xlsx.apply",
                    "XLSX-розклад застосовано та локально закріплено",
                    result,
                    actor="admin",
                )
                return self._send_json(200, result)

            if path == "/api/admin/action":
                action = str(body.get("action", "")).strip()
                if action == "sync":
                    result = ENGINE.sync_now(background=False)
                elif action == "poll_alerts":
                    result = ENGINE.poll_alerts()
                elif action == "alarm_on":
                    ENGINE.set_manual_alarm(True)
                    result = {"ok": True, "message": "Ручна тривога увімкнена"}
                elif action == "alarm_off":
                    ENGINE.set_manual_alarm(False)
                    result = {"ok": True, "message": "Ручна тривога вимкнена"}
                elif action == "test_silence":
                    ENGINE.test_silence()
                    result = {"ok": True, "message": "Тест хвилини мовчання запущено"}
                elif action == "refresh_weather":
                    weather = ENGINE.refresh_weather()
                    result = {
                        "ok": bool(weather.get("available")),
                        "message": "Погоду оновлено",
                        "weather": weather,
                    }
                elif action == "create_backup":
                    info = create_backup(
                        str(body.get("label", "")),
                        int(CONFIG.load().get("backup_keep_count", 14)),
                    )
                    write_event("backup.create", "Створено backup", info, actor="admin")
                    result = {"ok": True, "message": "Backup створено", "backup": info}
                elif action == "restore_backup":
                    info = restore_backup(str(body.get("name", "")))
                    reload_screens()
                    _restart_self()
                    write_event(
                        "backup.restore", "Backup відновлено", info, actor="admin"
                    )
                    result = {
                        "ok": True,
                        "message": "Backup відновлено; застосунок перезапускається",
                        "backup": info,
                    }
                elif action == "delete_backup":
                    changed = delete_backup(str(body.get("name", "")))
                    write_event(
                        "backup.delete",
                        "Backup видалено",
                        {"name": body.get("name", "")},
                        actor="admin",
                    )
                    result = {
                        "ok": True,
                        "message": "Backup видалено"
                        if changed
                        else "Backup не знайдено",
                    }
                elif action == "clear_logs":
                    clear_events()
                    write_event("log.clear", "Журнал очищено", actor="admin")
                    result = {"ok": True, "message": "Журнал очищено"}
                elif action == "ota_check":
                    result = check_manifest(
                        str(CONFIG.load().get("ota_manifest_url", ""))
                    )
                elif action == "ota_apply":
                    cfg = CONFIG.load()
                    manifest = check_manifest(str(cfg.get("ota_manifest_url", "")))
                    if not manifest.get("ok"):
                        result = manifest
                    elif not manifest.get("available") and not bool(
                        body.get("force", False)
                    ):
                        result = {
                            "ok": True,
                            "message": "Встановлена актуальна версія",
                            "manifest": manifest,
                        }
                    else:
                        backup = create_backup(
                            "pre-ota", int(CONFIG.load().get("backup_keep_count", 14))
                        )
                        write_event(
                            "ota.start",
                            "Початок OTA-оновлення",
                            {
                                "target": manifest.get("version"),
                                "backup": backup.get("name"),
                                "release_snapshot": "transaction snapshot",
                            },
                            actor="admin",
                        )
                        TELEGRAM.notify(
                            f"⬆️ LyceumTV OTA: початок оновлення до {manifest.get('version')}."
                        )
                        applied = apply_package(
                            manifest["package_url"],
                            manifest["sha256"],
                            manifest["version"],
                        )

                        write_event(
                            "ota.applied",
                            "OTA package підготовлено; очікується запуск нової версії",
                            {
                                "target": manifest.get("version"),
                                "release_snapshot": "transaction snapshot",
                            },
                            actor="admin",
                        )
                        result = {
                            **applied,
                            "target": manifest.get("version"),
                            "backup": backup,
                            "release_snapshot": "transaction snapshot",
                            "auto_rollback": True,
                        }
                        _restart_self()
                elif action == "telegram_test":
                    result = TELEGRAM.test()
                elif action == "telegram_reconnect":
                    result = TELEGRAM.reconnect()
                elif action == "restart_app":
                    write_event(
                        "service.restart",
                        "Перезапуск LyceumTV з адмінки",
                        actor="admin",
                    )
                    TELEGRAM.notify("♻️ LyceumTV: перезапуск із Control Center.")
                    result = {"ok": True, "message": "LyceumTV перезапускається"}
                    _restart_self()
                else:
                    return self._send_json(400, {"ok": False, "error": "Невідома дія"})
                return self._send_json(200, result)

        except Exception as exc:
            write_event(
                "admin.error",
                "Помилка Smart Campus",
                {"path": path, "error": str(exc)},
                actor="admin",
            )
            return self._send_json(400, {"ok": False, "error": str(exc)})

        return self._send_json(404, {"ok": False, "error": "Not found"})

    def _serve_static(self, path: str):
        rel = path.lstrip("/")
        if any(part.startswith(".") for part in Path(rel).parts):
            return self.send_error(403)
        target = (PUBLIC / rel).resolve()
        if PUBLIC.resolve() not in target.parents and target != PUBLIC.resolve():
            return self.send_error(403)
        if not target.is_file():
            return self.send_error(404)
        if target.is_relative_to((PUBLIC / "media").resolve()):
            return send_media(self, target)
        raw = target.read_bytes()
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.name.endswith(".webmanifest"):
            ctype = "application/manifest+json"
        self.send_response(200)
        self.send_header(
            "Content-Type",
            ctype
            + (
                "; charset=utf-8"
                if ctype.startswith(
                    (
                        "text/",
                        "application/javascript",
                        "application/json",
                        "application/manifest+json",
                    )
                )
                else ""
            ),
        )
        self.send_header("Content-Length", str(len(raw)))
        self.send_header(
            "Cache-Control",
            "no-cache"
            if target.suffix in (".html", ".js", ".css")
            else "public, max-age=86400",
        )
        self.end_headers()
        self.wfile.write(raw)


_OPS_MONITOR_STOP = threading.Event()
_OPS_LAST_ALERT_SIG = ""


def _ops_monitor_loop() -> None:
    global _OPS_LAST_ALERT_SIG
    while not _OPS_MONITOR_STOP.wait(180):
        try:
            cfg = CONFIG.load()
            if not cfg.get("health_alerts_enabled", True):
                continue
            state = ENGINE.get_state()
            screens = list_screens(int(cfg.get("screen_offline_seconds", 60) or 60))
            alerts = health_alerts(system_status(), screens, state, cfg)
            sig = "|".join(
                sorted(
                    str(x.get("code", "")) + ":" + str(x.get("message", ""))
                    for x in alerts
                )
            )
            if sig and sig != _OPS_LAST_ALERT_SIG:
                message = "⚠️ LyceumTV Health\n" + "\n".join(
                    "• " + str(x.get("message", "")) for x in alerts
                )
                write_event(
                    "health.warning",
                    "Smart Operations health alert",
                    {"alerts": alerts},
                    actor="system",
                )
                TELEGRAM.notify(message)
            _OPS_LAST_ALERT_SIG = sig
        except Exception as exc:
            write_event(
                "health.monitor.error",
                "Помилка health monitor",
                {"error": str(exc)},
                actor="system",
            )


def main() -> None:
    cfg = CONFIG.load()
    # The LAN entry point is the TLS proxy, including when an old config is restored.
    host = "127.0.0.1"
    port = int(cfg.get("port", 8080))
    write_event(
        "service.start",
        "LyceumTV 3.7.2 Smart Information Display запущено",
        {"host": host, "port": port},
    )
    TELEGRAM.start()
    _OPS_MONITOR_STOP.clear()
    threading.Thread(
        target=_ops_monitor_loop, daemon=True, name="smart-ops-health"
    ).start()
    httpd = BoundedHTTPServer((host, port), Handler)

    def stop(*_):
        try:
            threading.Thread(target=httpd.shutdown, daemon=True).start()
        except Exception:
            pass

    signal.signal(signal.SIGTERM, stop)
    print(
        f"LyceumTV 3.7.2 Smart Information Display listening on http://{host}:{port}",
        flush=True,
    )
    try:
        httpd.serve_forever(poll_interval=0.5)
    finally:
        _OPS_MONITOR_STOP.set()
        TELEGRAM.stop()
        ENGINE.stop()
        httpd.server_close()


if __name__ == "__main__":
    main()
