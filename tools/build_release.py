"""Verify and create a clean, reproducible release ZIP using only the stdlib."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from version import VERSION

TOP_FILES = {
    "README.md",
    "launcher.py",
    "CHANGELOG.md",
    "VERIFY_PROJECT.py",
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    ".gitignore",
    ".prettierignore",
    "INSTALL_TO_ORANGEPI.ps1",
    "INSTALL_RELEASE_ORANGEPI.ps1",
    "CHECK_ORANGEPI.ps1",
    "CHECK_SECURITY_ORANGEPI.ps1",
    "OPEN_ADMIN.ps1",
    "FIX_KIOSK_ORANGEPI.ps1",
    "HIDE_CURSOR_ORANGEPI.ps1",
}
DIRECTORIES = (
    "server",
    "public",
    "scripts",
    "data/default",
    "docs",
    "tests",
    "tools",
    "reports",
)


def release_files(root=ROOT):
    root = Path(root)
    paths = [root / name for name in TOP_FILES] + [root / "data/config.example.json"]
    for directory in DIRECTORIES:
        paths.extend((root / directory).rglob("*"))
    result = {}
    for path in paths:
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root).as_posix()
        if path.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}:
            raise ValueError(
                "Secret key material must stay outside release directories: " + rel
            )
        if any(
            part in {"__pycache__", ".ruff_cache", ".pytest_cache"}
            for part in path.parts
        ):
            continue
        if rel.startswith("public/media/") or path.suffix in {".pyc", ".pyo"}:
            continue
        result[rel] = path.read_bytes()
    return result


def build(output):
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    subprocess.run(
        [sys.executable, str(ROOT / "VERIFY_PROJECT.py")], cwd=ROOT, env=env, check=True
    )
    files = release_files()
    manifest = {
        name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(files.items())
    }
    files["PACKAGE_SHA256.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode()
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    folder = f"LyceumTV-{VERSION}-ORANGEPI-PC"
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        for name, raw in sorted(files.items()):
            info = zipfile.ZipInfo(folder + "/" + name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (0o100755 if name.endswith(".sh") else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, raw)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip():
            raise ValueError("ZIP CRC check failed")
        for name, wanted in manifest.items():
            if hashlib.sha256(archive.read(folder + "/" + name)).hexdigest() != wanted:
                raise ValueError("Archive hash mismatch: " + name)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_name(output.name + ".sha256").write_text(
        digest + "  " + output.name + "\n"
    )
    print(f"READY: {output} ({output.stat().st_size} bytes, {len(files)} files)")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "dist" / f"LyceumTV-{VERSION}-ORANGEPI-PC.zip",
    )
    build(parser.parse_args().output)
