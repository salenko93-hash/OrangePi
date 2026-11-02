"""Check the target before changing packages, services or boot configuration."""

from pathlib import Path
import platform
import argparse
import json
import os
import shutil
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


def inspect_storage(root, package_bytes=0):
    """Read metadata only. Never create directories or repair live permissions."""
    root = Path(root)
    installed = (root / "launcher.py").is_file()
    missing = []
    for path in (
        root,
        root / "data",
        root / "data/current",
        root / "data/backups",
        root / "data/logs",
        root / "public/media",
    ):
        if path.is_symlink():
            raise ValueError("Linked installation directory: " + str(path))
        if not path.exists():
            missing.append(str(path))
        elif not path.is_dir() or path.stat().st_mode & 0o002:
            raise ValueError("Unsafe directory or world-writable path: " + str(path))
    if root.exists() and not installed and any(root.iterdir()):
        raise ValueError(
            "Non-empty partial installation; inspect manually before installing"
        )
    if installed:
        import pwd

        uid = pwd.getpwnam("lyceumtv").pw_uid
        for path in (root, root / "data", root / "public/media"):
            if path.exists() and path.stat().st_uid != uid:
                raise ValueError(
                    "Unexpected owner; no automatic recursive repair: " + str(path)
                )
        config = root / "data/config.json"
        if config.exists() and (config.is_symlink() or config.stat().st_mode & 0o077):
            raise ValueError("Local config must be private and not linked")
    existing = root
    while not existing.exists():
        existing = existing.parent
    protected_size = 0
    for base in (root / "data", root / "public/media"):
        if not base.exists():
            continue

        def denied(error):
            raise error

        for directory, subdirs, names in os.walk(
            base, onerror=denied, followlinks=False
        ):
            current = Path(directory)
            subdirs[:] = [
                n
                for n in subdirs
                if current / n
                not in {
                    root / "data/backups",
                    root / "data/update_jobs",
                    root / "data/logs",
                }
            ]
            if any((current / n).is_symlink() for n in subdirs + names):
                raise ValueError("Linked local data requires manual review")
            protected_size += sum((current / n).stat().st_size for n in names)
    required = max(64 * 1024 * 1024, package_bytes * 3) + protected_size
    free = shutil.disk_usage(existing).free
    if free < required:
        raise ValueError(f"Insufficient free space: {free} bytes, need {required}")
    dependencies = ("python3", "bash", "sudo", "curl", "openssl", "rsync")
    absent = [name for name in dependencies if not shutil.which(name)]
    if absent and (installed or not shutil.which("apt-get")):
        raise ValueError("Missing dependencies: " + ", ".join(absent))
    return {
        "installed": installed,
        "missing_directories": missing,
        "free_bytes": free,
        "required_bytes": required,
        "dependencies_to_install": absent,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--root", type=Path, default=Path("/opt/lyceumtv"))
    parser.add_argument("--package-bytes", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        if sys.version_info < (3, 10):
            raise ValueError("Python 3.10+ is required.")
        model_file = Path("/proc/device-tree/model")
        model = model_file.read_text().rstrip("\x00\n") if model_file.exists() else ""
        validate_target(platform.machine(), platform.freedesktop_os_release(), model)
        if args.check_only:
            print(
                json.dumps(
                    {
                        "ok": True,
                        "model": model,
                        **inspect_storage(args.root, args.package_bytes),
                    }
                )
            )
        else:
            print(
                "Orange Pi PC preflight passed:",
                model or platform.machine(),
                flush=True,
            )
    except (OSError, ValueError, KeyError) as error:
        print("Preflight:", error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
