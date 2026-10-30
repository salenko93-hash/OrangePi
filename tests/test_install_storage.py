"""Run the actual storage/migration stage as an unprivileged application user."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(
    not hasattr(os, "geteuid") or os.geteuid() == 0 or not shutil.which("bash"),
    "requires a normal POSIX user and bash to exercise permission failures",
)
class InstallStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "app"
        (self.root / "data").mkdir(parents=True)
        shutil.copytree(ROOT / "data/default", self.root / "data/default")
        shutil.copy2(
            ROOT / "data/config.example.json", self.root / "data/config.example.json"
        )
        (self.root / "public").mkdir()
        (self.root / "server").mkdir()
        shutil.copy2(
            ROOT / "server/runtime_data.py", self.root / "server/runtime_data.py"
        )
        shutil.copy2(
            ROOT / "server/install_config.py", self.root / "server/install_config.py"
        )
        (self.root / "scripts").mkdir()
        (self.root / "scripts/install.sh").write_text("#!/bin/bash\n")
        self.staging = Path(self.tmp.name) / "saved"
        self.staging.mkdir()
        script = (ROOT / "scripts/install.sh").read_text()
        # The real sudo restore has already run; exercise all following storage operations.
        self.stage = script[
            script.index(
                "# Prepare application-owned storage before config and calendar migrations."
            ) :
        ]
        self.stage = self.stage.split("# The network service has no SSH identity", 1)[0]
        self.calendar_code = script.split("<<'PYCAL'\n", 1)[1].split("\nPYCAL", 1)[0]

    def run_stage(self):
        # Emulate privilege only for operations on this user's own temporary files.
        # Real installation uses sudo for files owned by root/other users.
        shell = 'INSTALL_DIR=$1; TMP_CFG=$2; PI_IP=192.0.2.77; USER_NAME=$(id -un); GROUP_NAME=$(id -gn); sudo(){ "$@"; };\n'
        result = subprocess.run(
            [
                "bash",
                "-eu",
                "-c",
                shell + self.stage,
                "test-install",
                str(self.root),
                str(self.staging),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_fresh_install_creates_writable_runtime_storage(self):
        self.run_stage()
        for directory in ("data/current", "data/backups", "data/logs", "public/media"):
            self.assertTrue(os.access(self.root / directory, os.W_OK), directory)
        self.assertEqual((self.root / "data/config.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.root / "data/smart_ops.json").stat().st_uid, os.getuid())
        for name in (
            "calendar.json",
            "schedule_numerator.json",
            "schedule_denominator.json",
        ):
            self.assertTrue(os.access(self.root / "data/current" / name, os.W_OK))

    def test_read_only_upgrade_preserves_config_media_and_live_schedules(self):
        shutil.copytree(self.root / "data/default", self.root / "data/current")
        calendar = self.root / "data/current/calendar.json"
        calendar.write_text(
            json.dumps({"source": "структура навчального року", "old": True})
        )
        calendar.chmod(0o444)
        import sys

        failed = subprocess.run(
            [
                sys.executable,
                "-c",
                self.calendar_code,
                str(calendar),
                str(self.root / "data/default/calendar.json"),
            ],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("PermissionError", failed.stderr)
        saved = {
            "slideshow_music_url": "/media/keep.mp3",
            "slideshow_title": "Keep title",
            "slideshow_volume_percent": 42,
            "mobile_public_url": "https://school.example/mobile/",
        }
        (self.root / "data/config.json").write_text(json.dumps(saved))
        (self.staging / "config.json").write_text(json.dumps(saved))
        schedules = {
            p.name: p.read_bytes()
            for p in (self.root / "data/current").glob("*numerator.json")
        }
        (self.root / "data/smart_ops.json").write_text('{"media":[{"id":"keep"}]}')
        (self.root / "public/media").mkdir()
        media = self.root / "public/media/keep.mp3"
        media.write_bytes(b"keep uploaded audio")
        for path in (self.root / "data").rglob("*"):
            if path.is_file():
                path.chmod(0o444)
        for path in sorted((self.root / "data").rglob("*"), reverse=True):
            if path.is_dir():
                path.chmod(0o555)
        (self.root / "data").chmod(0o555)
        self.run_stage()
        self.assertEqual(
            calendar.read_bytes(),
            (self.root / "data/default/calendar.json").read_bytes(),
        )
        current = json.loads((self.root / "data/config.json").read_text())
        for key, value in saved.items():
            self.assertEqual(current[key], value)
        self.assertGreaterEqual(len(current["admin_key"]), 32)
        self.assertEqual(media.read_bytes(), b"keep uploaded audio")
        self.assertEqual(
            json.loads((self.root / "data/smart_ops.json").read_text()),
            {"media": [{"id": "keep"}]},
        )
        for name, raw in schedules.items():
            self.assertEqual((self.root / "data/current" / name).read_bytes(), raw)
        self.assertEqual((self.root / "data/config.json").stat().st_mode & 0o777, 0o600)

    def test_custom_calendar_is_preserved_after_permissions_repair(self):
        (self.root / "data/current").mkdir()
        calendar = self.root / "data/current/calendar.json"
        raw = b'{"source":"custom-import.xlsx","custom":true}'
        calendar.write_bytes(raw)
        calendar.chmod(0o444)
        self.run_stage()
        self.assertEqual(calendar.read_bytes(), raw)
        self.assertTrue(os.access(calendar, os.W_OK))
