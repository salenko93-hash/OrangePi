from __future__ import annotations
from version import VERSION
import hashlib
import json
import os
import ssl
import tempfile
import urllib.request
import zipfile
import re
from release_signature import verify_manifest_signature
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

PRESERVE_PREFIXES = (
    "data/config.json",
    "data/runtime.json",
    "data/control.json",
    "data/calendar_override.json",
    "data/bells_override.json",
    "data/screens.json",
    "data/smart_ops.json",
    "public/media/",
    "data/imports/",
    "data/current/",
    "data/previous/",
    "data/backups/",
    "data/logs/",
    "data/release_backups/",
)


def _https(url: str) -> str:
    url = str(url or "").strip()
    if not url.startswith("https://"):
        raise ValueError("OTA URL має бути HTTPS")
    return url


def _download(url: str, timeout: int = 30, limit: int = 128 * 1024 * 1024) -> bytes:
    req = urllib.request.Request(
        _https(url), headers={"User-Agent": f"LyceumTV-RPi/{VERSION}"}
    )
    with urllib.request.urlopen(
        req, timeout=timeout, context=ssl.create_default_context()
    ) as r:
        _https(r.geturl())
        code = getattr(r, "status", 200)
        if code < 200 or code >= 300:
            raise RuntimeError(f"HTTP {code}")
        raw = r.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("OTA перевищує дозволений розмір")
        return raw


def current_version() -> str:
    try:
        return str(
            json.loads((DATA / "config.example.json").read_text(encoding="utf-8")).get(
                "version", ""
            )
        )
    except Exception:
        return ""


def version_tuple(value: str) -> tuple[int, ...]:
    parts = []
    for p in str(value or "").split("."):
        try:
            parts.append(int(p))
        except Exception:
            break
    return tuple(parts)


def check_manifest(url: str) -> dict[str, Any]:
    if not str(url or "").strip():
        return {
            "ok": False,
            "configured": False,
            "message": "OTA manifest URL не налаштовано",
            "current": current_version(),
        }
    raw = _download(url, limit=64 * 1024)
    obj = json.loads(raw.decode("utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("OTA manifest має бути JSON object")
    verify_manifest_signature(obj)
    version = str(obj.get("version", "")).strip()
    package_url = str(obj.get("package_url", "")).strip()
    sha256 = str(obj.get("sha256", "")).strip().lower()
    if not version or not package_url or not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ValueError("OTA manifest: потрібні version, package_url, sha256")
    _https(package_url)
    available = version_tuple(version) > version_tuple(current_version())
    return {
        "ok": True,
        "configured": True,
        "current": current_version(),
        "version": version,
        "available": available,
        "package_url": package_url,
        "sha256": sha256,
        "notes": str(obj.get("notes", "")),
    }


def _safe_zip_member(name: str) -> bool:
    p = Path(name)
    return (
        not p.is_absolute()
        and ".." not in p.parts
        and "\\" not in name
        and ":" not in name
    )


def apply_package(
    package_url: str, expected_sha256: str, expected_version: str | None = None
) -> dict[str, Any]:
    supervisor = ROOT / "data/launcher.pid"
    try:
        os.kill(int(supervisor.read_text()), 0)
        command = Path("/proc") / supervisor.read_text().strip() / "cmdline"
        if command.exists() and (
            b"launcher.py" not in command.read_bytes()
            or str(ROOT).encode() not in command.read_bytes()
        ):
            raise ValueError("Supervisor PID does not belong to this installation")
    except (OSError, ValueError):
        raise ValueError(
            "Для OTA потрібен запуск через launcher.py; встановіть нову systemd-службу"
        )
    raw = _download(package_url, timeout=90)
    digest = hashlib.sha256(raw).hexdigest()
    if digest.lower() != str(expected_sha256 or "").strip().lower():
        raise ValueError("OTA SHA-256 mismatch")

    with tempfile.TemporaryDirectory(prefix="lyceumtv-ota-") as td:
        td_path = Path(td)
        archive = td_path / "update.zip"
        archive.write_bytes(raw)
        extract = td_path / "extract"
        extract.mkdir()
        with zipfile.ZipFile(archive) as zf:
            if (
                len(zf.infolist()) > 4096
                or sum(info.file_size for info in zf.infolist()) > 256 * 1024 * 1024
            ):
                raise ValueError("OTA ZIP завеликий після розпакування")
            for info in zf.infolist():
                if not _safe_zip_member(info.filename):
                    raise ValueError("Небезпечний шлях у OTA ZIP")
            zf.extractall(extract)

        candidates = []
        if (extract / "server/app.py").is_file():
            candidates.append(extract)
        for child in extract.iterdir():
            if child.is_dir() and (child / "server/app.py").is_file():
                candidates.append(child)
        if len(candidates) != 1:
            raise ValueError("OTA ZIP повинен містити один LyceumTV project")
        source = candidates[0]

        from update_transaction import prepare, validate_release

        if (
            expected_version is not None
            and validate_release(source) != expected_version
        ):
            raise ValueError("Версія ZIP не відповідає OTA manifest")
        return prepare(ROOT, source)
