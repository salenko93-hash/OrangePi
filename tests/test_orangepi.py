"""Orange Pi deployment decisions, using disposable files and no sudo."""

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from install_config import migrate


def script_module(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / (name + ".py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


browser = script_module("kiosk_browser")
display = script_module("display_mode")
preflight = script_module("deployment_preflight")


class OrangePiTests(unittest.TestCase):
    def test_tv_host_allows_tv_and_preview_but_blocks_other_origins_and_local_admin(
        self,
    ):
        for uri in (browser.TV_URL, "http://127.0.0.1:8080/slideshow-preview?lite=1"):
            self.assertTrue(browser.allowed_navigation(uri), uri)
        for uri in (
            "file:///etc/passwd",
            "https://example.org/",
            "http://127.0.0.1:8080/admin",
            "http://127.0.0.1:8080/ops",
            "http://127.0.0.1:9999/",
            "http://admin:secret@127.0.0.1:8080/",
            "http://127.0.0.1:broken/",
            "http://[invalid/",
            "javascript:alert(1)",
            "about:blank",
        ):
            self.assertFalse(browser.allowed_navigation(uri), uri)

    def test_hdmi_uses_only_an_advertised_mode_and_keeps_other_connectors(self):
        modes = [
            {"width": 1280, "height": 720, "refresh": value}
            for value in (50, 59.94, 60)
        ]
        self.assertEqual(
            display.choose_mode(
                [{"name": "HDMI-A-1", "enabled": True, "modes": modes}]
            ),
            ("HDMI-A-1", "1280x720@60.000000Hz"),
        )
        for output in (
            {"name": "HDMI-A-1", "enabled": False, "modes": modes},
            {"name": "DSI-1", "enabled": True, "modes": modes},
            {
                "name": "HDMI-A-1",
                "enabled": True,
                "modes": [{"width": 1920, "height": 1080, "refresh": 60}],
            },
        ):
            self.assertIsNone(display.choose_mode([output]))

    def test_preflight_accepts_the_users_armbian_and_rejects_wrong_arch_or_old_os(self):
        preflight.validate_target(
            "armv7l", {"ID": "ubuntu", "VERSION_ID": "26.04"}, "Xunlong Orange Pi PC"
        )
        preflight.validate_target(
            "armv7l", {"ID": "debian", "VERSION_ID": "13"}, "Xunlong Orange Pi PC"
        )
        for machine, distro, version, model in (
            ("x86_64", "ubuntu", "26.04", ""),
            ("aarch64", "ubuntu", "26.04", ""),
            ("armv7l", "ubuntu", "20.04", ""),
            ("armv7l", "debian", "11", ""),
            ("armv7l", "ubuntu", "26.04", "Orange Pi Zero"),
        ):
            with self.assertRaises(ValueError):
                preflight.validate_target(
                    machine, {"ID": distro, "VERSION_ID": version}, model
                )

    def test_installer_sets_the_actual_board_ip_for_mobile_qr_and_retains_custom_domain(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            live = Path(directory) / "config.json"
            cfg = migrate(live, ROOT / "data/config.example.json", "192.168.1.77")
            self.assertEqual(cfg["mobile_public_url"], "https://192.168.1.77/mobile/")
            cfg = migrate(live, ROOT / "data/config.example.json", "192.168.1.78")
            self.assertEqual(cfg["mobile_public_url"], "https://192.168.1.78/mobile/")
            cfg["mobile_public_url"] = "https://school.example.org/mobile/"
            cfg["alerts_token"] = "preserved-test-marker"
            live.write_text(json.dumps(cfg))
            migrated = migrate(live, ROOT / "data/config.example.json", "192.168.1.79")
            self.assertEqual(migrated["mobile_public_url"], cfg["mobile_public_url"])
            self.assertEqual(migrated["alerts_token"], cfg["alerts_token"])

    def test_no_pi5_ip_defaults_or_snap_installers_and_boot_files_are_preserved(self):
        installer = (ROOT / "scripts/install.sh").read_text()
        self.assertLess(
            installer.index("deployment_preflight.py"),
            installer.index("apt-get update"),
        )
        self.assertLess(
            installer.index('kiosk_browser.py" --check'),
            installer.index("systemctl stop"),
        )
        for forbidden in (
            "/boot/firmware",
            "cmdline.txt",
            "--no-sandbox",
            "snap install",
            "MemoryMax=768M",
        ):
            self.assertNotIn(forbidden, installer)
        for rel in (
            "INSTALL_TO_ORANGEPI.ps1",
            "CHECK_ORANGEPI.ps1",
            "CHECK_SECURITY_ORANGEPI.ps1",
            "OPEN_ADMIN.ps1",
            "scripts/install.sh",
            "scripts/configure_https.sh",
        ):
            self.assertNotIn("192.168.0.18", (ROOT / rel).read_text(), rel)
        for name in ("kiosk_browser.py", "display_mode.py", "tv-session.sh"):
            self.assertIn("/usr/local/lib/lyceumtv/" + name, installer)
        self.assertEqual(
            json.loads((ROOT / "data/config.example.json").read_text())[
                "mobile_public_url"
            ],
            "",
        )


if __name__ == "__main__":
    unittest.main()
