"""Role-key behavior for this deployment, without touching working config."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
import config_store


class ConfigKeyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.example = ROOT / "data/config.example.json"
        self.keys = {
            k: json.loads(self.example.read_text())[k]
            for k in ("admin_key", "dispatcher_key", "teacher_key")
        }
        self.live = self.data / "config.json"
        self.paths = patch.multiple(
            config_store,
            DATA=self.data,
            CONFIG_PATH=self.live,
            EXAMPLE_PATH=self.example,
        )
        self.paths.start()
        self.addCleanup(self.paths.stop)

    def test_fresh_config_generates_unique_private_keys(self):
        cfg = config_store.ConfigStore().load()
        self.assertTrue(all(len(cfg[k]) >= 32 for k in self.keys))
        self.assertEqual(len({cfg[k] for k in self.keys}), 3)

    def test_existing_config_keys_survive_normal_start(self):
        saved = {k: "custom-" + k for k in self.keys}
        self.live.write_text(json.dumps(saved))
        cfg = config_store.ConfigStore().load()
        self.assertEqual({k: cfg[k] for k in self.keys}, saved)

    def test_restored_legacy_defaults_rotate_on_start_without_losing_tokens(self):
        self.live.write_text(
            json.dumps(
                {
                    "admin_key": "lyceumtv-admin",
                    "dispatcher_key": "lyceumtv-dispatch",
                    "teacher_key": "lyceumtv-teacher",
                    "alerts_token": "keep-test-token",
                }
            )
        )
        first = config_store.ConfigStore().load()
        self.assertTrue(all(len(first[k]) >= 32 for k in self.keys))
        self.assertEqual(first["alerts_token"], "keep-test-token")
        second = config_store.ConfigStore().load()
        self.assertEqual(
            {k: first[k] for k in self.keys}, {k: second[k] for k in self.keys}
        )

    def test_public_config_hides_role_keys(self):
        store = config_store.ConfigStore()
        private = store.load()
        cfg = store.public()
        for key, value in {k: private[k] for k in self.keys}.items():
            self.assertNotIn(key, cfg)
            self.assertNotIn(value, json.dumps(cfg))

    def test_installer_preserves_custom_keys_and_generates_missing_keys(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                if self.live.exists():
                    self.live.unlink()
                if existing:
                    self.live.write_text(
                        json.dumps(
                            {
                                **{k: "old-" + k for k in self.keys},
                                "slideshow_title": "Keep title",
                                "mobile_public_url": "https://school.example/mobile/",
                            }
                        )
                    )
                subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "server/install_config.py"),
                        str(self.live),
                        str(self.example),
                    ],
                    check=True,
                    capture_output=True,
                )
                cfg = json.loads(self.live.read_text())
                if existing:
                    self.assertEqual(
                        {k: cfg[k] for k in self.keys},
                        {k: "old-" + k for k in self.keys},
                    )
                else:
                    self.assertTrue(all(len(cfg[k]) >= 32 for k in self.keys))
                if existing:
                    self.assertEqual(cfg["slideshow_title"], "Keep title")
                    self.assertEqual(
                        cfg["mobile_public_url"], "https://school.example/mobile/"
                    )
