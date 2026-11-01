from __future__ import annotations
import hashlib
import json
import os
import tempfile
import re
from release_signature import verify_manifest_signature
from github_releases import (
    API as OFFICIAL_API,
    official_asset,
    download,
    unpack,
    version_tuple as strict_version,
)
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
    return download(url, timeout=timeout, limit=limit)


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
    if not str(url or "").strip() or url == OFFICIAL_API:
        from official_updates import check

        return check(ROOT)
    official_asset(url)
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
    official_asset(package_url)
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
    official_asset(package_url)
    if expected_version is None or strict_version(expected_version) <= strict_version(
        current_version()
    ):
        raise ValueError("Same or older runtime version cannot be applied")
    if os.name != "posix":
        raise ValueError("OTA installation requires the Orange Pi POSIX supervisor")
    supervisor = ROOT / "data/launcher.pid"
    try:
        pid = int(supervisor.read_text())
        if pid <= 0:
            raise ValueError("Invalid supervisor PID")
        os.kill(pid, 0)
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
        source = unpack(raw, td_path / "extract", expected_version)
        from update_transaction import prepare

        return prepare(ROOT, source)
