import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import backup_manager


class BackupRestoreTests(unittest.TestCase):
    def test_rejects_links_before_any_restore(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                backups = root / "data/backups"
                backups.mkdir(parents=True)
                archive = backups / "bad.tar.gz"
                with tarfile.open(archive, "w:gz") as tar:
                    link = tarfile.TarInfo("data/config.json")
                    link.type = kind
                    link.linkname = "/tmp/outside"
                    tar.addfile(link)
                with patch.multiple(
                    backup_manager, ROOT=root, DATA=root / "data", BACKUP_DIR=backups
                ):
                    with self.assertRaises(ValueError):
                        backup_manager.restore_backup(archive.name)
                self.assertFalse((root / "data/config.json").exists())

    def test_failed_restore_returns_all_original_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            backups = data / "backups"
            backups.mkdir(parents=True)
            for name in ("config.json", "runtime.json"):
                (data / name).write_text('{"old":true}')
            archive = backups / "restore.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                for name in ("config.json", "runtime.json"):
                    raw = b'{"new":true}'
                    info = tarfile.TarInfo("data/" + name)
                    info.size = len(raw)
                    tar.addfile(info, io.BytesIO(raw))
            original = backup_manager.os.replace
            failed = False

            def fail_once(src, dst):
                nonlocal failed
                if str(dst) == str(data / "runtime.json") and not failed:
                    failed = True
                    raise OSError("injected restore failure")
                return original(src, dst)

            with (
                patch.multiple(
                    backup_manager, ROOT=root, DATA=data, BACKUP_DIR=backups
                ),
                patch.object(backup_manager.os, "replace", side_effect=fail_once),
            ):
                with self.assertRaises(OSError):
                    backup_manager.restore_backup(archive.name)
            for name in ("config.json", "runtime.json"):
                self.assertEqual(json.loads((data / name).read_text()), {"old": True})

    def test_restores_regular_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backups = root / "data/backups"
            backups.mkdir(parents=True)
            archive = backups / "good.tar.gz"
            raw = b'{"custom":true}'
            with tarfile.open(archive, "w:gz") as tar:
                info = tarfile.TarInfo("data/config.json")
                info.size = len(raw)
                tar.addfile(info, io.BytesIO(raw))
            with patch.multiple(
                backup_manager, ROOT=root, DATA=root / "data", BACKUP_DIR=backups
            ):
                backup_manager.restore_backup(archive.name)
            self.assertEqual(
                json.loads((root / "data/config.json").read_text()), {"custom": True}
            )
