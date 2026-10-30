"""Local data must not require a remote URL or hide configured sync failures."""

from datetime import datetime
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import engine
import sync_manager
from smart_ops import health_alerts


class SyncModeTests(unittest.TestCase):
    def make_engine(self, config):
        instance = engine.Engine.__new__(engine.Engine)
        instance.config_store = SimpleNamespace(load=lambda: config)
        instance._now = lambda: datetime(2026, 10, 30, 14, 30)
        return instance

    def test_unconfigured_sync_leaves_live_files_and_network_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            current = data / "current"
            current.mkdir()
            live = current / "content.json"
            live.write_bytes(b'{"announcements":[{"title":"Custom live content"}]}')
            original = live.read_bytes()
            with (
                patch.multiple(sync_manager, DATA=data, CURRENT=current),
                patch("sync_manager._download") as download,
                patch("sync_manager.tempfile.mkdtemp") as stage,
            ):
                for value in ("", "  \n"):
                    result = sync_manager.sync_bundle(value)
                    self.assertIsNone(result["ok"])
                    self.assertEqual(result["status"], "local")
                    self.assertFalse(result["enabled"])
                    self.assertEqual(health_alerts({}, [], {"sync": result}, {}), [])
                download.assert_not_called()
                stage.assert_not_called()
            self.assertEqual(live.read_bytes(), original)
            self.assertEqual(set(data.iterdir()), {current})

    def test_manual_local_status_does_not_claim_a_successful_remote_sync(self):
        instance = self.make_engine({"manifest_url": "", "sheets_url": ""})
        with patch("engine.write_event") as event:
            status = instance.sync_now(background=False)
        self.assertEqual(status["status"], "local")
        self.assertEqual(status["at"], "2026-10-30T14:30:00")
        self.assertEqual(event.call_args.args[0], "sync.local")

    def test_configured_source_failure_still_produces_a_health_error(self):
        instance = self.make_engine(
            {"manifest_url": "https://example.org/manifest.json"}
        )
        with patch(
            "sync_manager._download", side_effect=TimeoutError("test timeout")
        ) as download:
            status = instance.sync_now(background=True)
        download.assert_called_once_with("https://example.org/manifest.json")
        self.assertIs(status["ok"], False)
        self.assertIn("test timeout", status["message"])
        self.assertIn(
            "sync", [a["code"] for a in health_alerts({}, [], {"sync": status}, {})]
        )

    def test_incomplete_or_insecure_configuration_is_not_silently_disabled(self):
        download = Mock()
        with patch("sync_manager._download", download):
            with self.assertRaisesRegex(ValueError, "маніфесту"):
                sync_manager.sync_bundle("", "https://example.org/sheets")
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                sync_manager.sync_bundle("http://example.org/manifest.json")
        download.assert_not_called()
