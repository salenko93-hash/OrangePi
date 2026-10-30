"""Regressions for the Pi's inaccessible /run/user/<uid> under ProtectHome."""

import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class KioskIsolationTests(unittest.TestCase):
    def test_kiosk_can_use_only_its_own_runtime_without_exposing_other_homes(self):
        installer = (ROOT / "scripts/install.sh").read_text()
        kiosk = installer.split(
            "sudo tee /etc/systemd/system/lyceumtv-kiosk.service", 1
        )[1].split("\nEOF", 1)[0]
        self.assertIn("User=$KIOSK_USER", kiosk)
        self.assertIn("ProtectHome=tmpfs", kiosk)
        # A capability-marked Armbian binary must not gain capabilities on exec:
        # bubblewrap rejects non-root callers with unexpected permitted caps.
        self.assertIn("\nNoNewPrivileges=true\n", kiosk)
        # Empty bounding sets can make capability-marked distro binaries fail
        # execve with EPERM before no_new_privs can suppress the file caps.
        self.assertNotIn("\nCapabilityBoundingSet=\n", kiosk)
        self.assertIn("\nAmbientCapabilities=\n", kiosk)
        self.assertNotIn("ProtectHome=false", kiosk)
        self.assertIn("Requires=user-runtime-dir@$KIOSK_UID.service", kiosk)
        self.assertIn("After=user-runtime-dir@$KIOSK_UID.service", kiosk)
        runtime = re.search(r"^Environment=XDG_RUNTIME_DIR=(.+)$", kiosk, re.M)[1]
        self.assertIn("BindPaths=" + runtime, kiosk)
        app = installer.split("sudo tee /etc/systemd/system/lyceumtv.service", 1)[
            1
        ].split("\nEOF", 1)[0]
        self.assertIn("ProtectHome=true", app)
        self.assertIn("NoNewPrivileges=true", app)


@unittest.skipIf(
    not hasattr(os, "geteuid") or os.geteuid() == 0 or not shutil.which("bash"),
    "requires unprivileged Linux/bash for real filesystem access failures",
)
class KioskLauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lyceum-kiosk-runtime-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.runtime = self.root / "runtime"
        self.marker = self.root / "cage-called"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name, code in {
            "curl": "#!/bin/sh\nexit 0\n",
            "dbus-run-session": '#!/bin/sh\nshift\nexec "$@"\n',
            "cage": '#!/bin/sh\nprintf "%s\\n" "$XDG_RUNTIME_DIR" > "$KIOSK_TEST_RECORD"\nprintf "%s\\n" "$@" > "${KIOSK_TEST_RECORD}.args"\nprintf "%s\\n" "$XCURSOR_THEME" "$XCURSOR_PATH" "$WLR_NO_HARDWARE_CURSORS" > "${KIOSK_TEST_RECORD}.cursor"\n',
        }.items():
            path = self.bin / name
            path.write_text(code)
            path.chmod(0o755)
        # Replace only the compositor/session wrapper in this disposable copy.
        script = (
            (ROOT / "scripts/launch-kiosk.sh")
            .read_text()
            .replace("/usr/bin/cage", shlex.quote(str(self.bin / "cage")))
        )
        script = script.replace(
            "/usr/bin/dbus-run-session", shlex.quote(str(self.bin / "dbus-run-session"))
        )
        self.script = self.root / "launch.sh"
        self.script.write_text(script)

    def launch(self, cursor_environment=None):
        env = os.environ.copy()
        for name in ("XCURSOR_THEME", "XCURSOR_PATH", "WLR_NO_HARDWARE_CURSORS"):
            env.pop(name, None)
        if cursor_environment:
            env.update(cursor_environment)
        env.update(
            XDG_RUNTIME_DIR=str(self.runtime),
            KIOSK_TEST_RECORD=str(self.marker),
            PATH=str(self.bin) + os.pathsep + env.get("PATH", ""),
        )
        return subprocess.run(
            ["bash", str(self.script)],
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
        )

    def test_private_writable_runtime_starts_compositor_without_leaving_probe(self):
        self.runtime.mkdir(mode=0o700)
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.marker.read_text().strip(), str(self.runtime))
        args = Path(str(self.marker) + ".args").read_text().splitlines()
        self.assertEqual(args[args.index("-m") + 1], "last")
        self.assertFalse(list(self.runtime.glob(".lyceumtv-runtime-*")))

    def test_first_process_launch_and_conflicting_inherited_cursor_settings(self):
        self.runtime.mkdir(mode=0o700)
        for inherited in (
            None,
            {
                "XCURSOR_THEME": "Adwaita",
                "XCURSOR_PATH": "/usr/share/icons",
                "WLR_NO_HARDWARE_CURSORS": "0",
            },
        ):
            result = self.launch(inherited)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                Path(str(self.marker) + ".cursor").read_text().splitlines(),
                ["lyceumtv-invisible", "/usr/local/share/lyceumtv-cursors", "1"],
            )

    def test_missing_runtime_fails_before_compositor_starts(self):
        result = self.launch()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("XDG_RUNTIME_DIR", result.stderr)
        self.assertFalse(self.marker.exists())

    def test_read_only_runtime_has_clear_error_instead_of_cage_abort(self):
        self.runtime.mkdir(mode=0o700)
        self.runtime.chmod(0o500)
        self.addCleanup(self.runtime.chmod, 0o700)
        result = self.launch()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot write", result.stderr)
        self.assertFalse(self.marker.exists())

    def test_shared_runtime_is_rejected(self):
        self.runtime.mkdir(mode=0o700)
        self.runtime.chmod(0o755)
        result = self.launch()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("0700", result.stderr)
        self.assertFalse(self.marker.exists())
