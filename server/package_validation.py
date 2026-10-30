"""Validate the complete local content bundle before a release is accepted."""

import hashlib
from pathlib import Path

SCHEDULES = {
    "schedule_numerator.json",
    "schedule_denominator.json",
    "shelter_numerator.json",
    "shelter_denominator.json",
}


def verify_manifest(manifest, directory):
    if (
        not isinstance(manifest, dict)
        or not isinstance(manifest.get("schedules"), dict)
        or set(manifest["schedules"]) != SCHEDULES
    ):
        raise ValueError("Manifest must contain exactly four schedules")
    entries = list(manifest["schedules"].items())
    entries += [(key + ".json", manifest.get(key)) for key in ("calendar", "content")]
    for name, item in entries:
        if not isinstance(item, dict) or item.get("url") != name:
            raise ValueError("Invalid local manifest path: " + name)
        path = Path(directory) / name
        if not path.is_file() or hashlib.sha256(
            path.read_bytes()
        ).hexdigest() != item.get("sha256"):
            raise ValueError("SHA-256 mismatch: " + name)
