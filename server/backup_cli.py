"""Use the same backup implementation from the UI and systemd timer."""

import argparse
import json
from pathlib import Path
import shutil
from backup_manager import create_backup, DATA, BACKUP_DIR
from storage_lock import storage_lock
from timezone_utils import local_now


def daily():
    with storage_lock(DATA, "daily-backup"):
        cfg = json.loads((DATA / "config.json").read_text(encoding="utf-8-sig"))
        now = local_now(str(cfg.get("timezone", "Europe/Kyiv")))
        hour = int(cfg.get("daily_backup_hour", 3))
        if not cfg.get("daily_backup_enabled", True) or now.hour < hour:
            return None
        marker = DATA / "last_daily_backup"
        today = now.date().isoformat()
        if marker.exists() and marker.read_text().strip() == today:
            return None
        info = create_backup("daily", int(cfg.get("backup_keep_count", 14)))
        stage = marker.with_suffix(".tmp")
        stage.write_text(today + "\n")
        stage.replace(marker)
        return BACKUP_DIR / info["name"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["create", "daily"])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "daily":
        output = daily()
    else:
        cfg_path = DATA / "config.json"
        cfg = (
            json.loads(cfg_path.read_text(encoding="utf-8-sig"))
            if cfg_path.exists()
            else {}
        )
        info = create_backup("manual", int(cfg.get("backup_keep_count", 14)))
        output = BACKUP_DIR / info["name"]
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(output, args.output)
            output = args.output
    if output:
        print(output)
