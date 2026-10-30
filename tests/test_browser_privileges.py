"""Check the real Linux privilege ABI in a child, without changing the test runner."""

from contextlib import redirect_stderr
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "kiosk_privileges", ROOT / "scripts/kiosk_browser.py"
)
browser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(browser)


class BrowserPrivilegeTests(unittest.TestCase):
    def test_uninitialized_window_does_not_receive_a_fullscreen_request(self):
        class Window:
            def set_decorated(self, decorated):
                self.decorated = decorated

            def set_default_size(self, width, height):
                self.size = (width, height)

            def set_cursor_from_name(self, name):
                self.cursor = name

            def fullscreen(self):
                raise AssertionError("Cage must not configure an uninitialized surface")

            def present(self):
                self.presented = True

        window = Window()
        browser.present_kiosk_window(window)
        self.assertFalse(window.decorated)
        self.assertEqual(window.size, (1280, 720))
        self.assertTrue(window.presented)
        self.assertEqual(window.cursor, "none")

    @unittest.skipUnless(
        sys.platform == "linux" and os.geteuid() != 0, "unprivileged Linux child"
    )
    def test_real_child_verifies_no_new_privs_and_zero_capability_sets_without_gi(self):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/kiosk_browser.py"),
                "--check-privileges",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(result.stdout.split("Browser privileges:", 1)[1])["after"]
        self.assertEqual(state["NoNewPrivs"], "1")
        for key in ("CapInh", "CapPrm", "CapEff", "CapAmb"):
            self.assertEqual(int(state[key], 16), 0, key)

    def test_root_is_rejected_before_loading_gtk_or_webkit(self):
        with (
            patch.object(browser.os, "geteuid", return_value=0, create=True),
            patch.object(browser, "load_bindings") as bindings,
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(browser.main([]), 1)
            bindings.assert_not_called()

    def test_privilege_failure_stops_before_loading_gtk_or_webkit(self):
        with (
            patch.object(browser.os, "geteuid", return_value=1001, create=True),
            patch.object(browser, "browser_security_state", return_value={}),
            patch.object(
                browser,
                "drop_browser_privileges",
                side_effect=OSError("test permission denial"),
            ),
            patch.object(browser, "load_bindings") as bindings,
            redirect_stderr(io.StringIO()) as errors,
        ):
            self.assertEqual(browser.main([]), 1)
            self.assertIn("privilege setup failed", errors.getvalue())
            bindings.assert_not_called()

    def test_standalone_repair_contains_exact_canonical_browser_host(self):
        # PowerShell 5.1 needs BOM for the embedded non-ASCII GTK window title.
        self.assertTrue(
            (ROOT / "FIX_KIOSK_ORANGEPI.ps1").read_bytes().startswith(b"\xef\xbb\xbf")
        )
        script = (ROOT / "FIX_KIOSK_ORANGEPI.ps1").read_text()
        embedded = script.split("<<'PYHOST'\n", 1)[1].split("\nPYHOST", 1)[0].rstrip()
        self.assertEqual(
            embedded, (ROOT / "scripts/kiosk_browser.py").read_text().rstrip()
        )
