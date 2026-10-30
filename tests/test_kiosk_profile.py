"""Exercise the real kiosk directory setup on private disposable directories."""

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "kiosk_profile", ROOT / "scripts/kiosk_profile.py"
)
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


@unittest.skipUnless(hasattr(os, "getuid"), "POSIX directory descriptor operations")
class KioskProfileTests(unittest.TestCase):
    def test_standalone_repair_contains_the_same_safe_profile_preparation(self):
        source = (
            (ROOT / "scripts/kiosk_profile.py")
            .read_text()
            .split("\ndef main():", 1)[0]
            .rstrip()
        )
        repair = (ROOT / "FIX_KIOSK_ORANGEPI.ps1").read_text()
        embedded = (
            repair.split("<<'PYPROFILE'\n", 1)[1]
            .split("\nimport pwd\naccount =", 1)[0]
            .rstrip()
        )
        self.assertEqual(embedded, source)

    def test_fresh_setup_and_upgrade_make_every_parent_private_and_writable(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            profile.prepare_profile(home, os.getuid(), os.getgid())
            paths = [home, *[path for path in home.rglob("*") if path.is_dir()]]
            for path in paths:
                self.assertEqual(path.stat().st_uid, os.getuid())
                self.assertEqual(path.stat().st_mode & 0o777, 0o700)
            # This mkdir failed on the physical board because .cache was root-owned.
            marker = home / ".cache/mesa_shader_cache"
            marker.mkdir()
            (home / ".cache").chmod(0o755)
            profile.prepare_profile(home, os.getuid(), os.getgid())
            self.assertEqual((home / ".cache").stat().st_mode & 0o777, 0o700)
            self.assertTrue(marker.is_dir())

    def test_linked_parent_is_rejected_without_changing_its_external_target(self):
        with tempfile.TemporaryDirectory() as directory:
            home, outside = Path(directory) / "home", Path(directory) / "outside"
            home.mkdir()
            outside.mkdir(mode=0o755)
            outside.chmod(0o755)
            (home / ".cache").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(OSError):
                profile.prepare_profile(home, os.getuid(), os.getgid())
            self.assertEqual(outside.stat().st_mode & 0o777, 0o755)
            self.assertEqual(list(outside.iterdir()), [])

    def test_linked_home_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            outside = Path(directory) / "outside"
            outside.mkdir(mode=0o755)
            outside.chmod(0o755)
            link = Path(directory) / "home"
            link.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(OSError):
                profile.prepare_profile(link, os.getuid(), os.getgid())
            self.assertEqual(outside.stat().st_mode & 0o777, 0o755)


if __name__ == "__main__":
    unittest.main()
