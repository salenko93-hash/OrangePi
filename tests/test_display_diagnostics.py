"""Diagnostic process snapshots must omit unrelated processes and credentials."""

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "display_diagnostics", ROOT / "scripts/display_diagnostics.py"
)
diag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diag)


class DisplayDiagnosticsTests(unittest.TestCase):
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
