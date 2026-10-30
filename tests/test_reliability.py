import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import backup_manager
import backup_cli
from config_store import ConfigStore
import config_store
from install_config import migrate
from media_library import cleanup, remove_unreferenced_url

ROOT = Path(__file__).resolve().parents[1]


class ConfigurationRecoveryTests(unittest.TestCase):
    def test_invalid_config_is_preserved_and_not_replaced(self):
        for raw in ('{"alerts_token":"secret",', "[]"):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as tmp:
                live = Path(tmp) / "config.json"
                live.write_text(raw)
                with self.assertRaises(ValueError):
                    migrate(live, ROOT / "data/config.example.json")
                self.assertEqual(live.read_text(), raw)
                self.assertEqual(len(list(Path(tmp).glob("config.json.invalid-*"))), 1)

    def test_valid_tokens_and_custom_settings_survive_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            live = Path(tmp) / "config.json"
            saved = {
                "alerts_token": "keep-alert",
                "telegram_bot_token": "keep-bot",
                "slideshow_music_url": "/media/song.mp3",
                "slideshow_volume_percent": 0,
            }
            live.write_text(json.dumps(saved))
            cfg = migrate(live, ROOT / "data/config.example.json")
            for key, value in saved.items():
                self.assertEqual(cfg[key], value)

    def test_running_config_load_and_save_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            live = data / "config.json"
            live.write_text("{broken")
            with patch.multiple(config_store, DATA=data, CONFIG_PATH=live):
                store = ConfigStore()
                with self.assertRaises(ValueError):
                    store.load()
                with self.assertRaises(ValueError):
                    store.save({"slideshow_title": "new"})
            self.assertEqual(live.read_text(), "{broken")


class BackupReliabilityTests(unittest.TestCase):
    def test_daily_and_manual_backups_share_listing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "daily-old.tar.gz").write_bytes(b"old")
            (root / "lyceumtv-backup-new.tar.gz").write_bytes(b"new")
            with patch.object(backup_manager, "BACKUP_DIR", root):
                self.assertEqual(len(backup_manager.list_backups()), 2)

    def test_same_second_backups_have_unique_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            data.mkdir()
            backups = data / "backups"
            (data / "config.json").write_text("{}")
            with patch.multiple(
                backup_manager, ROOT=root, DATA=data, BACKUP_DIR=backups
            ):
                first = backup_manager.create_backup("manual")
                second = backup_manager.create_backup("manual")
                self.assertNotEqual(first["name"], second["name"])
                self.assertEqual(len(backup_manager.list_backups()), 2)
                self.assertFalse(list(backups.glob("*.part")))

    def test_failed_backup_is_not_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            data.mkdir()
            (data / "config.json").write_text("{}")
            with (
                patch.multiple(
                    backup_manager, ROOT=root, DATA=data, BACKUP_DIR=data / "backups"
                ),
                patch("tarfile.TarFile.add", side_effect=OSError("disk error")),
            ):
                with self.assertRaises(OSError):
                    backup_manager.create_backup()
                self.assertEqual(backup_manager.list_backups(), [])

    def test_daily_backup_catches_up_after_a_missed_hour(self):
        from datetime import datetime

        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            (data / "config.json").write_text('{"daily_backup_hour":3}')
            with (
                patch.multiple(backup_cli, DATA=data, BACKUP_DIR=data / "backups"),
                patch.object(
                    backup_cli, "local_now", return_value=datetime(2026, 10, 28, 8, 0)
                ),
                patch.object(
                    backup_cli, "create_backup", return_value={"name": "new.tar.gz"}
                ) as create,
            ):
                self.assertIsNotNone(backup_cli.daily())
                create.assert_called_once()

    def test_midnight_is_a_valid_daily_backup_hour(self):
        from datetime import datetime

        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            (data / "config.json").write_text('{"daily_backup_hour":0}')
            with (
                patch.multiple(backup_cli, DATA=data, BACKUP_DIR=data / "backups"),
                patch.object(
                    backup_cli, "local_now", return_value=datetime(2026, 10, 28, 0, 5)
                ),
                patch.object(
                    backup_cli, "create_backup", return_value={"name": "new.tar.gz"}
                ) as create,
            ):
                self.assertIsNotNone(backup_cli.daily())
                create.assert_called_once()
                self.assertIsNone(backup_cli.daily())
                self.assertEqual(create.call_count, 1)


class MediaCleanupTests(unittest.TestCase):
    def test_only_unreferenced_old_files_are_cleaned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            media = root / "public/media"
            media.mkdir(parents=True)
            for name in ("used.mp4", "orphan.mp4", "fresh.mp4"):
                (media / name).write_bytes(b"file")
            for name in ("used.mp4", "orphan.mp4"):
                os.utime(media / name, (time.time() - 7200,) * 2)
            (root / "data/config.json").write_text(
                '{"slideshow_music_url":"/media/used.mp4"}'
            )
            preview = cleanup(root)
            self.assertEqual(preview["files"], 1)
            self.assertTrue((media / "orphan.mp4").exists())
            self.assertFalse(remove_unreferenced_url("/media/used.mp4", root))
            cleanup(root, dry_run=False)
            self.assertFalse((media / "orphan.mp4").exists())
            self.assertTrue((media / "used.mp4").exists())
            self.assertTrue((media / "fresh.mp4").exists())

    def test_corrupt_metadata_stops_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data/smart_ops.json").write_text("{bad")
            with self.assertRaises(ValueError):
                cleanup(root, dry_run=False)

    def test_path_traversal_and_symlinks_are_not_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / "public/media"
            media.mkdir(parents=True)
            outside = root / "keep"
            outside.write_text("keep")
            self.assertFalse(remove_unreferenced_url("/media/../../keep", root))
            self.assertTrue(outside.exists())
