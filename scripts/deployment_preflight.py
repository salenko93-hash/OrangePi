"""Check the target before changing packages, services or boot configuration."""

from pathlib import Path
import platform
import sys


def validate_target(machine, os_info, model=""):
    if machine not in {"armv7l", "armv8l"}:
        raise ValueError(
            "This release targets 32-bit Orange Pi PC (Allwinner H3 / armhf)."
        )
    distro = os_info.get("ID", "")
    major = int(os_info.get("VERSION_ID", "0").split(".")[0])
    if not (
        (distro == "ubuntu" and major >= 24) or (distro == "debian" and major >= 13)
    ):
        raise ValueError(
            "Use Armbian based on Ubuntu 24.04+ or Debian 13+ with WebKitGTK 6.0 packages."
        )
    if model and "orange pi pc" not in model.lower():
        raise ValueError("Unexpected board model: " + model)


def main():
    try:
        if sys.version_info < (3, 10):
            raise ValueError("Python 3.10+ is required.")
        model_file = Path("/proc/device-tree/model")
        model = model_file.read_text().rstrip("\x00\n") if model_file.exists() else ""
        validate_target(platform.machine(), platform.freedesktop_os_release(), model)
        print("Orange Pi PC preflight passed:", model or platform.machine(), flush=True)
    except (OSError, ValueError) as error:
        print("Preflight:", error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
