"""SSH bootstrap for an explicitly approved, SHA-256 verified OrangePi ZIP."""

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
import urllib.request
import zipfile


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--address", required=True)
    parser.add_argument("--approve", required=True)
    parser.add_argument("--allow-prerelease", action="store_true")
    args = parser.parse_args(argv)
    if args.approve != args.version or not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        raise ValueError("Exact administrator version approval is required")
    if args.archive.parent != Path("/tmp") or not re.fullmatch(
        r"orangepi-upload-[a-f0-9]{32}\.zip", args.archive.name
    ):
        raise ValueError("Unexpected private upload path")
    raw = args.archive.read_bytes()
    if len(raw) > 128 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != args.sha256:
        raise ValueError("SSH-uploaded ZIP SHA-256 mismatch")
    prefix = f"LyceumTV-{args.version}-ORANGEPI-PC/"
    try:
        with tempfile.TemporaryDirectory(prefix="orangepi-install-") as temporary:
            # Public, verified release code must be traversable by the service UID.
            Path(temporary).chmod(0o755)
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                infos = archive.infolist()
                if (
                    len(infos) > 4096
                    or sum(i.file_size for i in infos) > 256 * 1024 * 1024
                ):
                    raise ValueError("Release ZIP too large")
                names = set()
                for item in infos:
                    name = item.filename
                    path = PurePosixPath(name)
                    if (
                        not name.startswith(prefix)
                        or str(path) != name
                        or ".." in path.parts
                        or "\\" in name
                        or ":" in name
                        or item.is_dir()
                        or name.casefold() in names
                        or stat.S_IFMT(item.external_attr >> 16)
                        not in (0, stat.S_IFREG)
                    ):
                        raise ValueError("Unsafe release ZIP member")
                    names.add(name.casefold())
                manifest = json.loads(archive.read(prefix + "PACKAGE_SHA256.json"))
                if {i.filename for i in infos} != {prefix + n for n in manifest} | {
                    prefix + "PACKAGE_SHA256.json"
                }:
                    raise ValueError("Incomplete ZIP manifest")
                for name, wanted in manifest.items():
                    if (
                        hashlib.sha256(archive.read(prefix + name)).hexdigest()
                        != wanted
                    ):
                        raise ValueError("Release member hash mismatch")
                for item in infos:
                    destination = Path(temporary) / item.filename
                    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
                    destination.write_bytes(archive.read(item))
                    destination.chmod(0o755 if destination.suffix == ".sh" else 0o644)
            source = Path(temporary) / prefix.rstrip("/")
            subprocess.run(
                [
                    "sudo",
                    sys.executable,
                    str(source / "scripts/deployment_preflight.py"),
                    "--check-only",
                    "--package-bytes",
                    str(len(raw)),
                ],
                check=True,
            )
            if Path("/opt/lyceumtv/launcher.py").is_file():
                command = [
                    "sudo",
                    "-u",
                    "lyceumtv",
                    sys.executable,
                    str(source / "scripts/github_update.py"),
                    "--root",
                    "/opt/lyceumtv",
                    "apply",
                    "--tag",
                    args.tag,
                    "--approve",
                    args.version,
                ]
                if args.allow_prerelease:
                    command.append("--allow-prerelease")
                subprocess.run(command, check=True)
            else:
                # Fresh install only: existing local data is never recursively repaired.
                subprocess.run(
                    ["bash", str(source / "scripts/install.sh"), args.address],
                    check=True,
                )
                with urllib.request.urlopen(
                    "http://127.0.0.1:8080/api/health", timeout=5
                ) as response:
                    health = json.load(response)
                if (
                    health.get("ok") is not True
                    or health.get("service") != "LyceumTV"
                    or health.get("version") != args.version
                ):
                    raise ValueError(
                        "Installed service failed the exact-version health check"
                    )
    finally:
        args.archive.unlink(missing_ok=True)  # Only this uniquely named upload.
    print("PASS: approved OrangePi release installed and health checked")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print("FAIL:", error, file=sys.stderr)
        raise SystemExit(1)
