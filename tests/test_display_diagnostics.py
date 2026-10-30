"""Diagnostic process snapshots must omit unrelated processes and credentials."""

import importlib.util
import os
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "display_diagnostics", ROOT / "scripts/display_diagnostics.py"
)
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)


class DisplayDiagnosticsTests(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("LYCEUMTV_TEST_WLROOTS_LIBRARY"),
        "optional native wlroots fixture",
    )
    def test_native_probe_reports_transparent_pixels_without_a_display(self):
        spec = importlib.util.spec_from_file_location(
            "diagnostic_cursor_theme", ROOT / "scripts/hide_cursor.py"
        )
        theme = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(theme)
        with tempfile.TemporaryDirectory() as directory:
            theme.install(Path(directory))
            env = os.environ.copy()
            env["XCURSOR_PATH"] = str(Path(directory) / theme.SEARCH_PATH)
            env.pop("WAYLAND_DISPLAY", None)
            env.pop("DISPLAY", None)
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    diag.NATIVE_CURSOR_PROBE,
                    env["LYCEUMTV_TEST_WLROOTS_LIBRARY"],
                ],
                env=env,
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            report = json.loads(result.stdout)
            self.assertEqual(report["uid"], os.geteuid())
            self.assertEqual(len(report["cursors"]), 6)
            self.assertTrue(
                all(
                    item["loaded"] and item["visible_alpha"] is False
                    for item in report["cursors"]
                )
            )

    def test_environment_filters_credentials_and_only_keeps_display_settings(self):
        result = diag.filtered_environment(
            b"XCURSOR_THEME=default\0ADMIN_KEY=secret-marker\0WAYLAND_DISPLAY=wayland-0\0TELEGRAM_TOKEN=private-marker\0"
        )
        self.assertEqual(
            result, {"XCURSOR_THEME": "default", "WAYLAND_DISPLAY": "wayland-0"}
        )

    def test_process_snapshot_does_not_emit_argv_or_unrelated_account_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            for pid, comm in (("100", "cage"), ("101", "other")):
                path = proc / pid
                path.mkdir()
                (path / "comm").write_text(comm)
                (path / "cmdline").write_bytes(b"command\0private-command-argument\0")
                (path / "environ").write_bytes(
                    b"XCURSOR_PATH=/cursor\0ADMIN_KEY=secret-marker\0"
                )
                (path / "status").write_text(
                    f"Uid:\t{os.getuid()}\t{os.getuid()}\t{os.getuid()}\t{os.getuid()}\n"
                    "PPid:\t1\nNoNewPrivs:\t1\nCapEff:\t0000\nName:\tignored\n"
                )
                (path / "cgroup").write_text("0::/system.slice/lyceumtv-kiosk.service")
            result = diag.processes(os.getuid(), proc)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["pid"], 100)
            self.assertNotIn("secret-marker", str(result))
            self.assertNotIn("private-command-argument", str(result))
            self.assertEqual(result[0]["environment"], {"XCURSOR_PATH": "/cursor"})
