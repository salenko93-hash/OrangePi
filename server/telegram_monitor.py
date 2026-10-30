from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Callable

from event_log import write_event
from screen_manager import list_screens
from system_monitor import system_status


class TelegramMonitor:
    """Telegram notifications + long-poll command receiver.

    Runtime goals:
    - make command polling observable instead of silently swallowing errors;
    - automatically remove a webhook before getUpdates (Telegram forbids both);
    - recover from temporary network/API failures;
    - keep bot secrets out of diagnostics;
    - accept commands only from configured Chat ID.
    """

    def __init__(
        self,
        config_store,
        *,
        state_cb: Callable[[], dict[str, Any]],
        sync_cb: Callable[[], dict[str, Any]],
        restart_cb: Callable[[], None],
        version_cb: Callable[[], str],
    ) -> None:
        self.config_store = config_store
        self.state_cb = state_cb
        self.sync_cb = sync_cb
        self.restart_cb = restart_cb
        self.version_cb = version_cb

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._offset = 0
        self._screen_state: dict[str, bool] | None = None
        self._temp_alerted = False
        self._sync_error_key = ""

        self._diag_lock = threading.RLock()
        self._prepared_token_hash = ""
        self._diag: dict[str, Any] = {
            "thread_alive": False,
            "enabled": False,
            "commands_enabled": False,
            "configured": False,
            "polling": False,
            "prepared": False,
            "bot_username": "",
            "last_poll_at": "",
            "last_update_at": "",
            "last_command": "",
            "last_command_at": "",
            "last_error": "",
            "last_error_at": "",
            "last_prepare_at": "",
            "offset": 0,
        }

    @staticmethod
    def _iso_now() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    def _diag_set(self, **patch: Any) -> None:
        with self._diag_lock:
            self._diag.update(patch)

    def status(self) -> dict[str, Any]:
        cfg = self._cfg()
        token = str(cfg.get("telegram_bot_token", "") or "").strip()
        chat_id = str(cfg.get("telegram_chat_id", "") or "").strip()
        with self._diag_lock:
            out = dict(self._diag)
        out.update(
            {
                "thread_alive": bool(self._thread and self._thread.is_alive()),
                "enabled": bool(cfg.get("telegram_enabled", False)),
                "commands_enabled": bool(cfg.get("telegram_commands_enabled", False)),
                "configured": bool(token and chat_id),
                "chat_id_set": bool(chat_id),
                "token_set": bool(token),
                "offset": int(self._offset),
            }
        )
        return out

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="LyceumTV-Telegram",
            daemon=True,
        )
        self._thread.start()
        self._diag_set(thread_alive=True)

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._diag_set(thread_alive=False, polling=False)

    def reconnect(self) -> dict[str, Any]:
        """Force a fresh Bot API preparation.

        Safe to call after changing token/chat/commands in Control Center.
        """
        self._prepared_token_hash = ""
        self._offset = 0
        self._diag_set(
            prepared=False,
            polling=False,
            last_error="",
            last_error_at="",
            offset=0,
        )
        cfg = self._cfg()
        if not bool(cfg.get("telegram_enabled", False)):
            return {
                "ok": True,
                "message": "Telegram monitoring вимкнено",
                "telegram": self.status(),
            }
        if not bool(cfg.get("telegram_commands_enabled", False)):
            return {
                "ok": True,
                "message": "Telegram увімкнено, але команди вимкнені",
                "telegram": self.status(),
            }
        try:
            self._prepare_bot(cfg, force=True)
            return {
                "ok": True,
                "message": "Telegram command channel перепідключено",
                "telegram": self.status(),
            }
        except Exception as exc:
            self._record_error(exc)
            return {
                "ok": False,
                "message": f"Telegram command channel: {exc}",
                "telegram": self.status(),
            }

    def _cfg(self) -> dict[str, Any]:
        try:
            return self.config_store.load()
        except Exception:
            return {}

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16] if token else ""

    @staticmethod
    def _api(
        token: str,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: int = 15,
    ) -> dict[str, Any]:
        token = str(token or "").strip()
        if not token:
            raise ValueError("Telegram bot token не налаштовано")

        url = f"https://api.telegram.org/bot{token}/{method}"
        data = urllib.parse.urlencode(params or {}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "User-Agent": "LyceumTV/3.5.1",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", "replace")
            except Exception:
                pass
            try:
                obj = json.loads(body)
                desc = str(obj.get("description", "") or "")
            except Exception:
                desc = body
            msg = f"Telegram HTTP {exc.code}"
            if desc:
                msg += f": {desc[:500]}"
            raise RuntimeError(msg) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Telegram network error: {getattr(exc, 'reason', exc)}"
            ) from exc

        try:
            obj = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise RuntimeError("Telegram API повернув не-JSON відповідь") from exc

        if not isinstance(obj, dict) or not obj.get("ok"):
            desc = str(
                obj.get("description")
                if isinstance(obj, dict)
                else "Telegram API error"
            )
            raise RuntimeError(desc)
        return obj

    def _record_error(self, exc: Exception) -> None:
        msg = str(exc)[:900] or type(exc).__name__
        self._diag_set(last_error=msg, last_error_at=self._iso_now(), polling=False)

    def _clear_error(self) -> None:
        self._diag_set(last_error="", last_error_at="")

    def _prepare_bot(self, cfg: dict[str, Any], *, force: bool = False) -> None:
        token = str(cfg.get("telegram_bot_token", "") or "").strip()
        chat_id = str(cfg.get("telegram_chat_id", "") or "").strip()
        if not token or not chat_id:
            raise ValueError("Вкажіть Telegram bot token і Chat ID")

        token_hash = self._token_hash(token)
        if not force and self._prepared_token_hash == token_hash:
            return

        me = self._api(token, "getMe", {}, timeout=10)
        bot = me.get("result") or {}
        username = str(bot.get("username", "") or "")

        # getUpdates cannot work while a webhook is configured.
        # drop_pending_updates=False keeps commands that the user has already sent.
        self._api(
            token,
            "deleteWebhook",
            {"drop_pending_updates": "false"},
            timeout=10,
        )

        self._prepared_token_hash = token_hash
        self._diag_set(
            prepared=True,
            bot_username=username,
            last_prepare_at=self._iso_now(),
            polling=False,
        )
        self._clear_error()
        write_event(
            "telegram.ready",
            "Telegram command channel готовий",
            {"bot": username, "chat_id_set": bool(chat_id)},
        )

    def send_to(
        self, chat_id: str, text: str, *, cfg: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        cfg = cfg or self._cfg()
        token = str(cfg.get("telegram_bot_token", "") or "").strip()
        chat_id = str(chat_id or "").strip()
        if not token or not chat_id:
            raise ValueError("Вкажіть Telegram bot token і Chat ID")
        return self._api(
            token,
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": str(text or "")[:3900],
                "disable_web_page_preview": "true",
            },
            timeout=12,
        )

    def send(self, text: str, *, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
        cfg = cfg or self._cfg()
        chat_id = str(cfg.get("telegram_chat_id", "") or "").strip()
        return self.send_to(chat_id, text, cfg=cfg)

    def test(self) -> dict[str, Any]:
        cfg = self._cfg()
        commands = bool(cfg.get("telegram_commands_enabled", False))
        suffix = (
            "\nКоманди: увімкнені. Надішліть /ping або /status."
            if commands
            else "\nКоманди: ВИМКНЕНІ у Control Center."
        )
        self.send(
            "✅ LyceumTV 3.5.1 Smart Campus\nTelegram monitoring працює." + suffix,
            cfg=cfg,
        )
        return {
            "ok": True,
            "message": "Тестове повідомлення Telegram надіслано",
            "telegram": self.status(),
        }

    def notify(self, text: str) -> None:
        cfg = self._cfg()
        if not bool(cfg.get("telegram_enabled", False)):
            return
        try:
            self.send(text, cfg=cfg)
        except Exception as exc:
            self._record_error(exc)

    def _format_status(self) -> str:
        cfg = self._cfg()
        st = self.state_cb() or {}
        sy = system_status()
        screens = list_screens(int(cfg.get("screen_offline_seconds", 60) or 60))
        online = sum(1 for x in screens if x.get("online"))
        temp = sy.get("cpu_temp_c")
        sync = st.get("sync") or {}
        sync_text = "OK" if sync.get("ok") is not False else "ПОМИЛКА"
        return (
            f"📺 LyceumTV {self.version_cb()}\n"
            f"Режим: {st.get('mode', '—')}\n"
            f"CPU: {temp if temp is not None else '—'} °C\n"
            f"Екрани: {online}/{len(screens)} online\n"
            f"Sync: {sync_text}\n"
            f"IP: {', '.join(sy.get('ips') or []) or '—'}"
        )

    def _format_screens(self) -> str:
        cfg = self._cfg()
        screens = list_screens(int(cfg.get("screen_offline_seconds", 60) or 60))
        if not screens:
            return "📺 Екрани Smart Campus ще не зареєстровані."
        lines = ["📺 Екрани:"]
        for s in screens[:30]:
            mark = "🟢" if s.get("online") else "🔴"
            lines.append(
                f"{mark} {s.get('name') or s.get('id')} • "
                f"{s.get('profile', 'schedule')} • {s.get('ip') or '—'}"
            )
        return "\n".join(lines)

    def _help_text(self) -> str:
        return (
            "LyceumTV Smart Campus\n"
            "/ping — перевірка командного каналу\n"
            "/status — стан системи\n"
            "/screens — екрани\n"
            "/version — версія LyceumTV\n"
            "/sync — синхронізація\n"
            "/restart — перезапуск LyceumTV\n"
            "/help — список команд"
        )

    def _handle_command(
        self,
        text: str,
        cfg: dict[str, Any],
        *,
        reply_chat_id: str,
    ) -> None:
        cmd = str(text or "").strip().split()[0].lower()
        if "@" in cmd:
            cmd = cmd.split("@", 1)[0]

        self._diag_set(last_command=cmd, last_command_at=self._iso_now())
        write_event("telegram.command", f"Telegram команда: {cmd}", {"command": cmd})

        if cmd == "/ping":
            self.send_to(
                reply_chat_id, "🏓 PONG • LyceumTV Telegram commands ONLINE", cfg=cfg
            )
        elif cmd == "/status":
            self.send_to(reply_chat_id, self._format_status(), cfg=cfg)
        elif cmd == "/screens":
            self.send_to(reply_chat_id, self._format_screens(), cfg=cfg)
        elif cmd == "/version":
            self.send_to(reply_chat_id, f"LyceumTV {self.version_cb()}", cfg=cfg)
        elif cmd == "/sync":
            self.send_to(reply_chat_id, "🔄 Запускаю синхронізацію LyceumTV…", cfg=cfg)
            try:
                result = self.sync_cb()
                self.send_to(
                    reply_chat_id,
                    "✅ " + str(result.get("message") or "Синхронізацію завершено"),
                    cfg=cfg,
                )
            except Exception as exc:
                self.send_to(reply_chat_id, "❌ Sync: " + str(exc)[:600], cfg=cfg)
        elif cmd == "/restart":
            self.send_to(reply_chat_id, "♻️ LyceumTV перезапускається.", cfg=cfg)
            threading.Timer(1.0, self.restart_cb).start()
        elif cmd in {"/start", "/help"}:
            self.send_to(reply_chat_id, self._help_text(), cfg=cfg)
        else:
            self.send_to(
                reply_chat_id,
                "Невідома команда.\n\n" + self._help_text(),
                cfg=cfg,
            )

    def _poll_commands(self, cfg: dict[str, Any]) -> None:
        if not bool(cfg.get("telegram_commands_enabled", False)):
            self._diag_set(polling=False)
            return

        token = str(cfg.get("telegram_bot_token", "") or "").strip()
        allowed_chat = str(cfg.get("telegram_chat_id", "") or "").strip()
        if not token or not allowed_chat:
            self._diag_set(polling=False)
            return

        self._prepare_bot(cfg)

        self._diag_set(polling=True)
        obj = self._api(
            token,
            "getUpdates",
            {
                "offset": self._offset,
                "timeout": 10,
                "allowed_updates": json.dumps(["message"]),
            },
            timeout=15,
        )
        self._diag_set(last_poll_at=self._iso_now(), polling=True)
        self._clear_error()

        for update in obj.get("result", []) or []:
            update_id = int(update.get("update_id", 0) or 0)
            # Consume update before command side effects; if reply fails user can resend.
            self._offset = max(self._offset, update_id + 1)
            self._diag_set(offset=self._offset, last_update_at=self._iso_now())

            msg = update.get("message") or {}
            chat_id = str((msg.get("chat") or {}).get("id", "") or "")
            text = str(msg.get("text", "") or "")

            if chat_id != allowed_chat:
                continue
            if not text.startswith("/"):
                continue

            try:
                self._handle_command(text, cfg, reply_chat_id=chat_id)
            except Exception as exc:
                self._record_error(exc)
                write_event(
                    "telegram.command.error",
                    "Помилка Telegram-команди",
                    {"command": text[:80], "error": str(exc)[:500]},
                )
                try:
                    self.send_to(chat_id, "❌ LyceumTV: " + str(exc)[:600], cfg=cfg)
                except Exception:
                    pass

    def _monitor_conditions(self, cfg: dict[str, Any]) -> None:
        screens = list_screens(int(cfg.get("screen_offline_seconds", 60) or 60))
        current = {str(s.get("id")): bool(s.get("online")) for s in screens}
        if self._screen_state is None:
            self._screen_state = current
        else:
            for s in screens:
                sid = str(s.get("id"))
                before = self._screen_state.get(sid)
                now = bool(s.get("online"))
                if before is True and now is False:
                    self.notify(f"🔴 LyceumTV: екран «{s.get('name') or sid}» OFFLINE.")
                elif before is False and now is True:
                    self.notify(
                        f"🟢 LyceumTV: екран «{s.get('name') or sid}» знову ONLINE."
                    )
            self._screen_state = current

        sy = system_status()
        temp = sy.get("cpu_temp_c")
        threshold = float(cfg.get("telegram_cpu_temp_alert_c", 75) or 75)
        if temp is not None and float(temp) >= threshold:
            if not self._temp_alerted:
                self.notify(
                    f"🌡️ LyceumTV: температура Orange Pi {temp} °C "
                    f"(поріг {threshold:g} °C)."
                )
                self._temp_alerted = True
        elif temp is not None and float(temp) <= threshold - 5:
            self._temp_alerted = False

        state = self.state_cb() or {}
        sync = state.get("sync") or {}
        if sync.get("ok") is False:
            key = str(sync.get("error") or sync.get("message") or "sync_error")
            if key != self._sync_error_key:
                self.notify("❌ LyceumTV sync: " + key[:700])
                self._sync_error_key = key
        else:
            self._sync_error_key = ""

    def _loop(self) -> None:
        last_monitor = 0.0
        backoff = 2.0

        while not self._stop.is_set():
            cfg = self._cfg()
            enabled = bool(cfg.get("telegram_enabled", False))
            commands_enabled = bool(cfg.get("telegram_commands_enabled", False))
            token = str(cfg.get("telegram_bot_token", "") or "").strip()
            chat_id = str(cfg.get("telegram_chat_id", "") or "").strip()

            self._diag_set(
                enabled=enabled,
                commands_enabled=commands_enabled,
                configured=bool(token and chat_id),
                thread_alive=True,
            )

            if not enabled:
                self._diag_set(polling=False)
                self._stop.wait(3)
                continue

            try:
                if time.time() - last_monitor >= 30:
                    self._monitor_conditions(cfg)
                    last_monitor = time.time()

                if commands_enabled:
                    self._poll_commands(cfg)
                else:
                    self._diag_set(polling=False)

                backoff = 2.0
            except Exception as exc:
                self._record_error(exc)
                write_event(
                    "telegram.poll.error",
                    "Помилка Telegram polling",
                    {"error": str(exc)[:700]},
                )
                self._stop.wait(backoff)
                backoff = min(30.0, backoff * 1.7)
                continue

            # Long polling already waits up to 10 seconds; this is only a tiny yield.
            self._stop.wait(0.5)

        self._diag_set(thread_alive=False, polling=False)
