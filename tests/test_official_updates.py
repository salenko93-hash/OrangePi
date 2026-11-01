"""Official-source, backup, consent and hostile-release regressions."""

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import socket
import time
import tempfile
import unittest
from unittest.mock import patch
import urllib.request
import zipfile

import github_releases as github
import official_updates as official
import ota_manager
from test_update_transaction import fixture, supervisor

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "update_preflight", ROOT / "scripts/deployment_preflight.py"
)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


class OfficialUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "installed"
        self.source = Path(self.tmp.name) / "source"
        fixture(self.root, "3.5.0")
        fixture(self.source, "3.5.1")
        (self.root / "data/config.json").write_text('{"local":"keep-private"}')
        (self.root / "data/current").mkdir()
        (self.root / "data/current/schedule.json").write_text('{"local":"schedule"}')
        (self.root / "public/media").mkdir()
        (self.root / "public/media/local.mp4").write_bytes(b"local-media")
        self.tag = "v3.5.1-rc.1"
        self.name = "LyceumTV-3.5.1-ORANGEPI-PC.zip"
        self.url = github.BASE + self.tag + "/" + self.name
        self.raw = self.zip()
        self.digest = hashlib.sha256(self.raw).hexdigest()
        self.info = {
            "version": "3.5.1",
            "tag": self.tag,
            "name": self.name,
            "package_url": self.url,
            "sha256": self.digest,
        }

    def zip(self, extra=None, symlink=False):
        stream = io.BytesIO()
        prefix = "LyceumTV-3.5.1-ORANGEPI-PC/"
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in self.source.rglob("*"):
                if path.is_file():
                    archive.writestr(
                        prefix + path.relative_to(self.source).as_posix(),
                        path.read_bytes(),
                    )
            if extra:
                item = zipfile.ZipInfo(extra)
                if symlink:
                    item.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(item, b"outside")
        return stream.getvalue()

    def metadata(self):
        return {
            "tag_name": self.tag,
            "prerelease": True,
            "draft": False,
            "assets": [
                {
                    "name": self.name,
                    "browser_download_url": self.url,
                    "digest": "sha256:" + self.digest,
                },
                {
                    "name": self.name + ".sha256",
                    "browser_download_url": self.url + ".sha256",
                },
            ],
        }

    def test_official_discovery_requires_opt_in_and_three_agreeing_hashes(self):
        metadata = self.metadata()

        def download(url, **kwargs):
            if url.startswith(github.API):
                return json.dumps(metadata).encode()
            if url.endswith(".sha256"):
                return (self.digest + "  " + self.name + "\n").encode()
            return self.raw

        with patch.object(github, "download", side_effect=download):
            with self.assertRaisesRegex(ValueError, "opt-in"):
                github.release(self.tag)
            info = github.release(self.tag, allow_prerelease=True)
            self.assertEqual(github.package(info), self.raw)
            metadata["assets"][0]["digest"] = "sha256:" + "0" * 64
            with self.assertRaisesRegex(ValueError, "disagree"):
                github.release(self.tag, allow_prerelease=True)

    def test_foreign_assets_downgrade_and_redirect_are_rejected(self):
        for url in (
            self.url.replace("OrangePi", "other"),
            "http://github.com/x",
            self.url + "?token=secret",
            self.url.replace("github.com", "github.com.evil.test"),
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                github.official_asset(url)
        handler = github.HTTPSRedirect()
        request = urllib.request.Request(self.url)
        for target in (
            "http://release-assets.githubusercontent.com/x",
            "https://evil.test/package",
        ):
            with self.assertRaises(ValueError):
                handler.redirect_request(request, None, 302, "", {}, target)
        with patch.object(github, "download", return_value=b"tampered"):
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                github.package(self.info)

    def test_zip_verification_rejects_traversal_links_duplicates_and_unlisted_files(
        self,
    ):
        for name, link in (
            ("../outside", False),
            ("LyceumTV-3.5.1-ORANGEPI-PC/public/link", True),
            ("LyceumTV-3.5.1-ORANGEPI-PC/unlisted", False),
            ("LyceumTV-3.5.1-ORANGEPI-PC/server/./app.py", False),
            ("LyceumTV-3.5.1-ORANGEPI-PC/SERVER/APP.PY", False),
        ):
            target = Path(self.tmp.name) / "rejected"
            with self.subTest(name=name), self.assertRaises(ValueError):
                github.unpack(self.zip(name, link), target, "3.5.1")
            self.assertFalse(target.exists())
        target = Path(self.tmp.name) / "valid"
        extracted = github.unpack(self.raw, target, "3.5.1")
        self.assertEqual(
            (extracted / "server/app.py").read_bytes(),
            (self.source / "server/app.py").read_bytes(),
        )

    def test_check_is_read_only_and_apply_requires_exact_consent_and_newer_version(
        self,
    ):
        with patch.object(github, "release", return_value=self.info):
            before = (self.root / "server/version.py").read_bytes()
            self.assertTrue(
                official.check(self.root, self.tag, allow_prerelease=True)["available"]
            )
            self.assertFalse((self.root / "data/logs").exists())
            with self.assertRaisesRegex(ValueError, "approve"):
                official.apply(self.root, self.tag, "wrong", allow_prerelease=True)
            self.assertEqual((self.root / "server/version.py").read_bytes(), before)
        with patch.object(
            github, "release", return_value={**self.info, "version": "3.5.0"}
        ):
            with self.assertRaisesRegex(ValueError, "Same or older"):
                official.apply(self.root, self.tag, "3.5.0", allow_prerelease=True)
        with patch.object(ota_manager, "current_version", return_value="3.5.1"):
            with self.assertRaisesRegex(ValueError, "Same or older"):
                ota_manager.apply_package(self.url, self.digest, "3.5.1")

    def test_verified_backup_covers_private_config_live_schedule_and_media(self):
        result = official.backup(self.root)
        archive = self.root / "data/backups" / result["name"]
        self.assertEqual(
            hashlib.sha256(archive.read_bytes()).hexdigest(), result["sha256"]
        )
        import tarfile

        with tarfile.open(archive) as source:
            self.assertEqual(
                source.extractfile("data/config.json").read(),
                b'{"local":"keep-private"}',
            )
            self.assertEqual(
                source.extractfile("data/current/schedule.json").read(),
                b'{"local":"schedule"}',
            )
            self.assertEqual(
                source.extractfile("public/media/local.mp4").read(), b"local-media"
            )
        if os.name == "posix":
            self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
        raw = archive.read_bytes()
        archive.write_bytes(raw[:-8] + b"invalid!")
        with self.assertRaises((OSError, EOFError)):
            official.verify_backup(archive)

    @unittest.skipUnless(os.name == "posix", "POSIX supervisor ownership check")
    def test_backup_failure_prevents_prepare_and_success_uses_existing_worker(self):
        pid = os.getpid()
        (self.root / "data/launcher.pid").write_text(str(pid))
        real_is_file = Path.is_file
        real_read = Path.read_bytes
        cmdline = Path("/proc") / str(pid) / "cmdline"

        def read(path):
            return (
                b"launcher.py\0" + str(self.root.resolve()).encode()
                if path == cmdline
                else real_read(path)
            )

        def is_file(path):
            return True if path == cmdline else real_is_file(path)

        with (
            patch.object(github, "release", return_value=self.info),
            patch.object(github, "package", return_value=self.raw),
            patch.object(Path, "read_bytes", read),
            patch.object(Path, "is_file", is_file),
            patch.object(official, "backup", side_effect=OSError("backup corrupt")),
            patch.object(official.transaction, "prepare") as prepare,
        ):
            with self.assertRaisesRegex(OSError, "backup corrupt"):
                official.apply(self.root, self.tag, "3.5.1", allow_prerelease=True)
            prepare.assert_not_called()
        with (
            patch.object(github, "release", return_value=self.info),
            patch.object(github, "package", return_value=self.raw),
            patch.object(Path, "read_bytes", read),
            patch.object(Path, "is_file", is_file),
            patch.object(official, "wait_result", return_value={"phase": "healthy"}),
        ):
            result = official.apply(self.root, self.tag, "3.5.1", allow_prerelease=True)
        self.assertTrue(result["ok"])
        self.assertEqual(
            official.transaction.read_state(self.root)["phase"], "prepared"
        )
        self.assertEqual(
            (self.root / "data/config.json").read_text(), '{"local":"keep-private"}'
        )

    @unittest.skipUnless(os.name == "posix", "POSIX supervised end-to-end update")
    def test_real_official_update_and_manual_rollback_preserve_local_data(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        config = json.dumps({"port": port, "local": "keep-private"})
        (self.root / "data/config.json").write_text(config)
        with tempfile.TemporaryFile() as log, supervisor(self.root, log):
            deadline = time.monotonic() + 8
            while not (self.root / "data/app.pid").exists():
                if time.monotonic() >= deadline:
                    self.fail("supervisor did not start the application")
                time.sleep(0.01)
            with (
                patch.object(github, "release", return_value=self.info),
                patch.object(github, "package", return_value=self.raw),
            ):
                result = official.apply(
                    self.root, self.tag, "3.5.1", allow_prerelease=True, timeout=20
                )
            self.assertEqual(result["result"]["phase"], "healthy")
            self.assertEqual(official.transaction.version_at(self.root), "3.5.1")
            restored = official.rollback(self.root, "rollback", timeout=20)
            self.assertEqual(restored["result"]["phase"], "rolled_back")
            self.assertEqual(official.transaction.version_at(self.root), "3.5.0")
            self.assertEqual((self.root / "data/config.json").read_text(), config)
            self.assertEqual(
                (self.root / "public/media/local.mp4").read_bytes(), b"local-media"
            )
            self.assertEqual(
                (self.root / "data/current/schedule.json").read_text(),
                '{"local":"schedule"}',
            )

    def test_preflight_never_repairs_partial_data_or_accepts_insufficient_space(self):
        fresh = Path(self.tmp.name) / "absent"
        with patch.object(preflight.shutil, "which", return_value="/usr/bin/tool"):
            result = preflight.inspect_storage(fresh, 1024)
        self.assertFalse(result["installed"])
        self.assertFalse(fresh.exists())
        partial = Path(self.tmp.name) / "partial"
        partial.mkdir()
        (partial / "keep").write_bytes(b"keep")
        with self.assertRaisesRegex(ValueError, "partial"):
            preflight.inspect_storage(partial)
        self.assertEqual((partial / "keep").read_bytes(), b"keep")
        usage = shutil.disk_usage(self.tmp.name)
        with patch.object(
            preflight.shutil,
            "disk_usage",
            return_value=type(usage)(usage.total, usage.used, 0),
        ):
            with self.assertRaisesRegex(ValueError, "free space"):
                preflight.inspect_storage(fresh)
