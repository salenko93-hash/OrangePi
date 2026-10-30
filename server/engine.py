from __future__ import annotations
from version import VERSION
import json
import ssl
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from urllib.parse import urlencode

from config_store import ConfigStore, RuntimeStore
from schedule_engine import build_schedule, active_announcements
from announcement_policy import after_school_info
from duty_rotation import duty_for_date
from sync_manager import sync_bundle
from event_log import write_event
from timezone_utils import local_now

ROOT = Path(__file__).resolve().parents[1]

WMO = {
    0: "Ясно",
    1: "Переважно ясно",
    2: "Мінлива хмарність",
    3: "Хмарно",
    45: "Туман",
    48: "Туман",
    51: "Мряка",
    53: "Мряка",
    55: "Мряка",
    56: "Крижана мряка",
    57: "Крижана мряка",
    61: "Невеликий дощ",
    63: "Дощ",
    65: "Сильний дощ",
    66: "Крижаний дощ",
    67: "Крижаний дощ",
    71: "Невеликий сніг",
    73: "Сніг",
    75: "Сильний сніг",
    77: "Сильний сніг",
    80: "Невеликі зливи",
    81: "Зливи",
    82: "Сильні зливи",
    85: "Снігові заряди",
    86: "Снігові заряди",
    95: "Гроза",
    96: "Гроза з градом",
    99: "Гроза з градом",
}


class Engine:
    def __init__(self, config: ConfigStore, runtime: RuntimeStore) -> None:
        self.config_store = config
        self.runtime_store = runtime
        self._lock = threading.RLock()
        rt = runtime.load()
        self.remote_alert_state = str(rt.get("remote_alert_state", "NONE"))
        self.manual_alarm = bool(rt.get("manual_alarm", False))
        self.alarm_started_at = rt.get("alarm_started_at")
        self.all_clear_until = float(rt.get("all_clear_until", 0) or 0)
        self.last_silence_date = str(rt.get("last_silence_date", ""))
        self.silence_until = float(rt.get("silence_until", 0) or 0)
        self.silence_event_id = str(rt.get("silence_event_id", ""))
        self.test_silence_until = 0.0
        self.test_silence_event_id = ""
        self.weather: dict[str, Any] = {"available": False, "condition": "Оновлення…"}
        self.sync_status: dict[str, Any] = {
            "ok": None,
            "message": "Ще не синхронізовано",
            "version": "",
            "at": "",
        }
        self.alert_status: dict[str, Any] = {
            "message": "UID 81 • запуск",
            "http": None,
            "at": "",
        }
        self._next_weather = 0.0
        self._next_alert = 0.0
        self._next_sync = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, name="LyceumTVEngine", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=3)

    def _now(self) -> datetime:
        cfg = self.config_store.load()
        return local_now(str(cfg.get("timezone", "Europe/Kyiv")))

    def _loop(self) -> None:
        while not self._stop.is_set():
            now_ts = time.time()
            cfg = self.config_store.load()
            try:
                self._timed_states(cfg)
                if (
                    bool(cfg.get("weather_enabled", True))
                    and now_ts >= self._next_weather
                ):
                    self.refresh_weather(cfg)
                if now_ts >= self._next_alert:
                    self.poll_alerts(cfg)
                if now_ts >= self._next_sync:
                    self.sync_now(background=True)
            except Exception:
                pass
            self._stop.wait(1.0)

    def _timed_states(self, cfg: dict[str, Any]) -> None:
        now = self._now()
        now_ts = time.time()
        alarm = self.alarm_active()
        if alarm:
            # Alarm has priority over memorial mode.
            self.silence_until = 0.0
            self.test_silence_until = 0.0
            return

        if not bool(cfg.get("minute_silence_enabled", True)):
            return
        target = str(cfg.get("minute_silence_time", "09:00")).strip()
        try:
            hh, mm = [int(x) for x in target.split(":", 1)]
        except Exception:
            hh, mm = 9, 0
        today = now.date().isoformat()
        if now.hour == hh and now.minute == mm and self.last_silence_date != today:
            self.last_silence_date = today
            self.silence_until = now_ts + 79.536
            self.silence_event_id = f"daily-{today}-{hh:02d}{mm:02d}"
            self.runtime_store.save(
                {
                    "last_silence_date": self.last_silence_date,
                    "silence_until": self.silence_until,
                    "silence_event_id": self.silence_event_id,
                }
            )

    def alarm_active(self) -> bool:
        return self.manual_alarm or self.remote_alert_state == "ACTIVE"

    def set_manual_alarm(self, enabled: bool) -> None:
        with self._lock:
            was = self.alarm_active()
            self.manual_alarm = bool(enabled)
            now_active = self.alarm_active()
            patch = {"manual_alarm": self.manual_alarm}
            if not was and now_active:
                self.alarm_started_at = self._now().isoformat()
                patch["alarm_started_at"] = self.alarm_started_at
                self.all_clear_until = 0.0
                patch["all_clear_until"] = 0
            elif was and not now_active:
                secs = max(
                    0, int(self.config_store.load().get("all_clear_seconds", 15))
                )
                self.all_clear_until = time.time() + secs
                patch["all_clear_until"] = self.all_clear_until
            self.runtime_store.save(patch)
            write_event(
                "alarm.manual",
                "Ручна тривога увімкнена" if enabled else "Ручна тривога вимкнена",
                {"active": self.alarm_active()},
                actor="admin",
            )

    def poll_alerts(self, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
        cfg = cfg or self.config_store.load()
        self._next_alert = time.time() + max(5, int(cfg.get("alerts_poll_seconds", 15)))
        token = str(cfg.get("alerts_token", "")).strip()
        uid = str(cfg.get("alerts_uid", "81"))
        if not token:
            self.alert_status = {
                "message": "API token не налаштовано",
                "http": None,
                "at": self._now().isoformat(),
            }
            return self.alert_status
        endpoint = (
            str(cfg.get("alerts_endpoint", "")).strip()
            or f"https://api.alerts.in.ua/v1/iot/active_air_raid_alerts/{uid}.json"
        )
        req = Request(
            endpoint,
            headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/json",
                "User-Agent": f"LyceumTV-RPi/{VERSION}",
            },
        )
        was = self.alarm_active()
        try:
            with urlopen(req, timeout=8, context=ssl.create_default_context()) as r:
                code = getattr(r, "status", 200)
                raw = r.read().decode("utf-8").strip().strip('"')
            if code < 200 or code >= 300:
                raise RuntimeError(f"HTTP {code}")
            if raw in ("A", "P"):
                state = "ACTIVE"
            elif raw == "N":
                state = "NONE"
            else:
                raise ValueError(f"Невідома відповідь: {raw}")
            self.remote_alert_state = state
            now_active = self.alarm_active()
            patch = {"remote_alert_state": state}
            if not was and now_active:
                self.alarm_started_at = self._now().isoformat()
                patch["alarm_started_at"] = self.alarm_started_at
                self.all_clear_until = 0
                patch["all_clear_until"] = 0
            elif was and not now_active:
                secs = max(0, int(cfg.get("all_clear_seconds", 15)))
                self.all_clear_until = time.time() + secs
                patch["all_clear_until"] = self.all_clear_until
            self.runtime_store.save(patch)
            if was != now_active:
                write_event(
                    "alarm.remote",
                    "Повітряна тривога" if now_active else "Відбій повітряної тривоги",
                    {"uid": uid, "raw": raw, "active": now_active},
                )
            self.alert_status = {
                "message": f"UID {uid} • {raw} • HTTP {code}",
                "http": code,
                "at": self._now().isoformat(),
            }
        except Exception as e:
            self.alert_status = {
                "message": f"Помилка API; стан збережено: {type(e).__name__}",
                "http": None,
                "at": self._now().isoformat(),
            }
        return self.alert_status

    def refresh_weather(self, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
        cfg = cfg or self.config_store.load()
        self._next_weather = time.time() + max(
            60, int(cfg.get("weather_refresh_seconds", 600))
        )
        params = urlencode(
            {
                "latitude": cfg.get("weather_latitude", 48.51),
                "longitude": cfg.get("weather_longitude", 32.26),
                "current": "temperature_2m,apparent_temperature,weather_code",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min",
                "forecast_days": 5,
                "timezone": cfg.get("timezone", "Europe/Kyiv"),
            }
        )
        url = "https://api.open-meteo.com/v1/forecast?" + params
        req = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": f"LyceumTV-RPi/{VERSION}",
            },
        )
        try:
            with urlopen(req, timeout=8, context=ssl.create_default_context()) as r:
                obj = json.loads(r.read().decode("utf-8"))
            cur = obj["current"]
            code = int(cur.get("weather_code", -1))
            daily = obj.get("daily", {})
            forecast = []
            dates = daily.get("time", []) or []
            codes = daily.get("weather_code", []) or []
            highs = daily.get("temperature_2m_max", []) or []
            lows = daily.get("temperature_2m_min", []) or []
            for i in range(min(len(dates), len(codes), len(highs), len(lows))):
                forecast.append(
                    {
                        "date": dates[i],
                        "code": codes[i],
                        "max": highs[i],
                        "min": lows[i],
                        "condition": WMO.get(int(codes[i]), "Погода"),
                    }
                )
            self.weather = {
                "available": True,
                "city": str(cfg.get("weather_city", "Кропивницький")),
                "temperature": round(float(cur.get("temperature_2m", 0))),
                "apparent": round(
                    float(cur.get("apparent_temperature", cur.get("temperature_2m", 0)))
                ),
                "code": code,
                "condition": WMO.get(code, "Поточна погода"),
                "forecast": forecast,
                "updated_at": self._now().isoformat(),
            }
        except Exception as e:
            if not self.weather.get("available"):
                self.weather = {
                    "available": False,
                    "city": str(cfg.get("weather_city", "Кропивницький")),
                    "condition": "Погода тимчасово недоступна",
                    "error": type(e).__name__,
                }
            self._next_weather = time.time() + 120
        return self.weather

    def sync_now(self, background: bool = False) -> dict[str, Any]:
        cfg = self.config_store.load()
        interval = max(60, int(cfg.get("sync_interval_seconds", 300)))
        self._next_sync = time.time() + interval
        try:
            result = sync_bundle(
                str(cfg.get("manifest_url", "")).strip(),
                str(cfg.get("sheets_url", "")).strip(),
                bool(cfg.get("pin_local_denominator", True)),
                list(cfg.get("pinned_local_schedules", []) or []),
            )
            self.sync_status = {**result, "at": self._now().isoformat()}
            if not background:
                local = result.get("status") == "local"
                write_event(
                    "sync.local" if local else "sync",
                    result["message"] if local else "Ручна синхронізація завершена",
                    {"version": result.get("version", "")},
                    actor="admin",
                )
        except Exception as e:
            self.sync_status = {
                "ok": False,
                "version": "",
                "message": f"Синхронізація не виконана: {e}",
                "at": self._now().isoformat(),
            }
            if not background:
                write_event(
                    "sync.error",
                    "Помилка ручної синхронізації",
                    {"error": str(e)},
                    actor="admin",
                )
        return self.sync_status

    def test_silence(self) -> None:
        now = time.time()
        self.test_silence_until = now + 79.536
        self.test_silence_event_id = f"test-{int(now * 1000)}"

    def get_state(self) -> dict[str, Any]:
        cfg = self.config_store.load()
        now = self._now()
        now_ts = time.time()
        alarm = self.alarm_active()
        silence_active = (not alarm) and (
            now_ts < self.silence_until or now_ts < self.test_silence_until
        )
        silence_event_id = (
            self.test_silence_event_id
            if now_ts < self.test_silence_until
            else self.silence_event_id
        )
        all_clear = (not alarm) and now_ts < self.all_clear_until
        schedule = build_schedule(now, cfg, shelter=alarm)
        duty = duty_for_date(now.date(), cfg)
        if silence_active:
            mode = "SILENCE"
        elif alarm:
            mode = "AIR_RAID"
        elif all_clear:
            mode = "ALL_CLEAR"
        else:
            mode = "NORMAL"
        announcement = ""
        after_school_window = after_school_info(now, schedule.get("phase", ""), mode)
        if mode == "NORMAL" and bool(cfg.get("break_announcements_enabled", True)):
            rotate = max(15, int(cfg.get("announcement_rotation_seconds", 45)))
            if after_school_window:
                # After the last scheduled lesson, cycle announcements and today's events
                # continuously until 17:00 local time. No lessons/holidays never trigger this.
                arr = active_announcements(include_today_events=True, now=now)
                if arr:
                    seconds_today = now.hour * 3600 + now.minute * 60 + now.second
                    announcement = arr[(seconds_today // rotate) % len(arr)]
            elif schedule.get("break_time"):
                seconds_to_next = int(schedule.get("seconds_to_next_lesson", 0))
                seconds_into = int(schedule.get("seconds_into_break", 0))
                if seconds_to_next > 60 and seconds_into % rotate >= max(
                    5, rotate - 15
                ):
                    arr = active_announcements(now=now)
                    if arr:
                        announcement = arr[(seconds_into // rotate) % len(arr)]
        return {
            "after_school_info": after_school_window,
            "after_school_until": now.replace(
                hour=17, minute=0, second=0, microsecond=0
            ).isoformat(),
            "app": {"name": "LyceumTV", "version": VERSION, "platform": "Orange Pi PC"},
            "now": now.isoformat(),
            "clock": now.strftime("%H:%M:%S"),
            "date": now.strftime("%d.%m.%Y"),
            "day_label": schedule.get("day_label", ""),
            "mode": mode,
            "schedule": schedule,
            "duty": duty,
            "weather": self.weather,
            "alarm": {
                "active": alarm,
                "remote_state": self.remote_alert_state,
                "manual": self.manual_alarm,
                "started_at": self.alarm_started_at,
                "event_id": self.alarm_started_at or "",
                "uid": str(cfg.get("alerts_uid", "81")),
                "status": self.alert_status,
                "sound_enabled": bool(cfg.get("alarm_sound_enabled", True)),
                "volume": max(0, min(100, int(cfg.get("alarm_volume_percent", 85))))
                / 100.0,
            },
            "silence": {
                "active": silence_active,
                "event_id": silence_event_id,
                "volume": max(
                    0, min(100, int(cfg.get("minute_silence_volume_percent", 25)))
                )
                / 100.0,
            },
            "all_clear": {
                "active": all_clear,
                "seconds": max(0, int(self.all_clear_until - now_ts)),
            },
            "announcement": announcement,
            "sync": self.sync_status,
            "config_public": self.config_store.public(),
        }
