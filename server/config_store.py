from __future__ import annotations
from media_library import MEDIA_LOCK
from json_cache import load_json
import json
import os
import threading
import tempfile
import math
from install_config import secure_keys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CONFIG_PATH = DATA / "config.json"
EXAMPLE_PATH = DATA / "config.example.json"
RUNTIME_PATH = DATA / "runtime.json"


class ConfigStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        DATA.mkdir(parents=True, exist_ok=True)
        if not CONFIG_PATH.exists():
            initial = load_json(EXAMPLE_PATH)
            secure_keys(initial)
            self._atomic_json(CONFIG_PATH, initial, mode=0o600)
            try:
                os.chmod(CONFIG_PATH, 0o600)
            except OSError:
                pass
        else:
            # Backups from older releases can contain known defaults too.
            # Corrupt existing JSON remains untouched and load() fails closed.
            try:
                saved = load_json(CONFIG_PATH)
                if not isinstance(saved, dict):
                    return
            except (OSError, ValueError):
                return
            secured = secure_keys(dict(saved))
            if secured != saved:
                self._atomic_json(CONFIG_PATH, secured, mode=0o600)

    def load(self) -> dict[str, Any]:
        with self._lock:
            defaults = load_json(EXAMPLE_PATH)
            release_version = str(defaults.get("version", ""))
            try:
                saved = load_json(CONFIG_PATH)
                if not isinstance(saved, dict):
                    raise ValueError("config.json must contain an object")
            except (OSError, ValueError) as error:
                raise ValueError(
                    "Конфігурація пошкоджена або недоступна; файл не змінено"
                ) from error
            defaults.update(saved)
            # The running software version belongs to the release, not to persisted admin settings.
            if release_version:
                defaults["version"] = release_version
            return defaults

    def save(self, patch: dict[str, Any]) -> dict[str, Any]:
        with MEDIA_LOCK, self._lock:
            current = self.load()
            template = load_json(EXAMPLE_PATH)
            allowed = set(current.keys()) - {"version"}
            for key, value in patch.items():
                if key in {"host", "port", "local_screen_token"}:
                    continue
                if key in {"admin_key", "dispatcher_key", "teacher_key"}:
                    if (
                        not isinstance(value, str)
                        or not 24 <= len(value.strip()) <= 256
                    ):
                        raise ValueError(
                            "Новий ключ має містити від 24 до 256 символів"
                        )
                    value = value.strip()
                    if any(
                        value == current.get(other)
                        for other in ("admin_key", "dispatcher_key", "teacher_key")
                        if other != key
                    ):
                        raise ValueError("Ключі різних ролей мають відрізнятися")
                if key in allowed:
                    expected = template.get(key)
                    if key in template:
                        valid = isinstance(value, type(expected))
                        if isinstance(expected, (int, float)) and not isinstance(
                            expected, bool
                        ):
                            valid = (
                                isinstance(value, (int, float))
                                and not isinstance(value, bool)
                                and math.isfinite(value)
                                and abs(value) <= 10**9
                            )
                        if not valid:
                            raise ValueError(f"Некоректний тип налаштування: {key}")
                        if isinstance(value, str) and len(value) > 4096:
                            raise ValueError(f"Налаштування завелике: {key}")
                        if isinstance(value, list) and len(value) > 256:
                            raise ValueError(f"Забагато елементів: {key}")
                    current[key] = value
            release_version = load_json(EXAMPLE_PATH).get("version")
            if release_version:
                current["version"] = release_version
            self._atomic_json(CONFIG_PATH, current, mode=0o600)
            return current

    def public(self) -> dict[str, Any]:
        cfg = self.load()
        out = dict(cfg)
        out.pop("local_screen_token", None)
        out.pop("alerts_token", None)
        out["alerts_token_set"] = bool(str(cfg.get("alerts_token", "")).strip())
        out.pop("telegram_bot_token", None)
        out["telegram_bot_token_set"] = bool(
            str(cfg.get("telegram_bot_token", "")).strip()
        )
        out.pop("admin_key", None)
        out.pop("dispatcher_key", None)
        out["dispatcher_key_set"] = bool(str(cfg.get("dispatcher_key", "")).strip())
        out.pop("teacher_key", None)
        out["teacher_key_set"] = bool(str(cfg.get("teacher_key", "")).strip())
        out.pop("cloud_mirror_token", None)
        out["cloud_mirror_token_set"] = bool(
            str(cfg.get("cloud_mirror_token", "")).strip()
        )
        return out

    @staticmethod
    def _atomic_json(
        path: Path, payload: dict[str, Any], mode: int | None = None
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # NamedTemporaryFile starts private; secrets are never briefly written
        # into a world-readable staging file before chmod.
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".config-", delete=False
        ) as output:
            tmp = Path(output.name)
            try:
                json.dump(payload, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
            except Exception:
                tmp.unlink(missing_ok=True)
                raise
        try:
            tmp.chmod(mode if mode is not None else 0o600)
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)


class RuntimeStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()

    def load(self) -> dict[str, Any]:
        with self._lock:
            try:
                data = load_json(RUNTIME_PATH)
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}

    def save(self, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            current = self.load()
            current.update(patch)
            ConfigStore._atomic_json(RUNTIME_PATH, current, mode=0o600)
            return current
