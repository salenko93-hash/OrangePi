"""Regressions for the false 'repair succeeded' result during a restart loop."""

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "kiosk_stability", ROOT / "scripts/kiosk_stability.py"
)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class KioskStabilityTests(unittest.TestCase):
    def test_active_restart_loop_is_rejected(self):
        snapshots = iter(
            [
                {
                    "ActiveState": "active",
                    "SubState": "running",
                    "MainPID": "100",
                    "NRestarts": "37",
                },
                {
                    "ActiveState": "active",
                    "SubState": "running",
                    "MainPID": "101",
                    "NRestarts": "38",
                },
            ]
        )
        with self.assertRaisesRegex(RuntimeError, "restarted"):
            check.wait_for_stable(
                seconds=2, read=lambda: next(snapshots), sleep=lambda _n: None
            )

    def test_stable_process_with_historical_restarts_is_accepted(self):
        state = {
            "ActiveState": "active",
            "SubState": "running",
            "MainPID": "101",
            "NRestarts": "38",
        }
        check.wait_for_stable(seconds=20, read=lambda: state, sleep=lambda _n: None)

    def test_active_without_a_main_process_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "not running"):
            check.require_running(
                {"ActiveState": "active", "SubState": "running", "MainPID": "0"}
            )
