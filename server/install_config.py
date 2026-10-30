"""Fail-closed configuration validation and deployment defaults migration."""

import argparse
from datetime import datetime
import json
import ipaddress
import os
from pathlib import Path
import shutil
import secrets
import uuid


def secure_keys(config):
    """Rotate only missing or publicly known legacy defaults; retain custom keys."""
    known = {"lyceumtv-admin", "lyceumtv-dispatch", "lyceumtv-teacher"}
    for role in ("admin_key", "dispatcher_key", "teacher_key"):
        value = config.get(role)
        if not isinstance(value, str) or not value.strip() or value in known:
            config[role] = secrets.token_urlsafe(32)
    if (
        not isinstance(config.get("local_screen_token"), str)
        or len(config["local_screen_token"]) < 32
    ):
        config["local_screen_token"] = secrets.token_urlsafe(32)
    return config


def read_existing(path):
    path = Path(path)
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError("JSON root must be an object")
        return value
    except (OSError, ValueError) as error:
        preserved = path.with_name(
            path.name
            + ".invalid-"
            + datetime.now().strftime("%Y%m%d-%H%M%S")
            + "-"
            + uuid.uuid4().hex[:8]
        )
        try:
            shutil.copy2(path, preserved)
            preserved.chmod(0o600)
        except OSError:
            preserved = path
        raise ValueError(
            f"Конфігурація не читається. Встановлення зупинено; файл збережено: {preserved}. Відновіть коректний JSON або резервну копію."
        ) from error


def migrate(live, example, public_ip=None):
    live = Path(live)
    saved = read_existing(live)
    defaults = json.loads(Path(example).read_text(encoding="utf-8-sig"))
    cfg = {**defaults, **saved}
    if str(cfg.get("mobile_public_url", "")).strip().rstrip("/") in {
        "http://192.168.1.228:8080/mobile",
        "http://192.168.2.193:8080/mobile",
    }:
        cfg["mobile_public_url"] = defaults["mobile_public_url"]
    secure_keys(cfg)
    # HTTPS proxy is the only LAN entry point. Never retain a legacy LAN bind.
    cfg["host"] = "127.0.0.1"
    cfg["port"] = 8080
    if str(cfg.get("mobile_public_url", "")).startswith("http://192.168."):
        cfg["mobile_public_url"] = defaults["mobile_public_url"]
    if public_ip:
        address = str(ipaddress.IPv4Address(public_ip))
        from urllib.parse import urlsplit

        existing_url = str(cfg.get("mobile_public_url", "")).strip()
        try:
            old_host = urlsplit(existing_url).hostname or ""
            ipaddress.IPv4Address(old_host)
            is_ip_url = True
        except ValueError:
            is_ip_url = False
        # Keep deliberately configured public domain URLs; refresh local IP URLs.
        if not existing_url or is_ip_url:
            cfg["mobile_public_url"] = f"https://{address}/mobile/"
    cfg["version"] = defaults["version"]
    if cfg == saved:
        live.chmod(0o600)
        return cfg
    live.parent.mkdir(parents=True, exist_ok=True)
    stage = live.with_name(live.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        descriptor = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(cfg, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(stage, live)
    finally:
        stage.unlink(missing_ok=True)
    return cfg


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("live", type=Path)
    parser.add_argument("example", type=Path, nargs="?")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--public-ip", help="Board IPv4 address for the mobile QR URL")
    args = parser.parse_args()
    try:
        if args.check:
            read_existing(args.live)
        elif args.example:
            migrate(args.live, args.example, args.public_ip)
        else:
            parser.error("example is required for migration")
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + "\n")
