import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import event_log


class EventTailTests(unittest.TestCase):
    def test_tail_matches_previous_results_for_large_unicode_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            lines = [
                json.dumps(
                    {"index": i, "message": "Повідомлення " + ("я" * 200)},
                    ensure_ascii=False,
                )
                for i in range(3000)
            ]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with patch.object(event_log, "LOG_PATH", path):
                for limit in (1, 20, 120, 1000):
                    self.assertEqual(
                        event_log.read_events(limit),
                        [json.loads(line) for line in reversed(lines[-limit:])],
                    )

    def test_long_or_malformed_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.write_text(json.dumps({"message": "я" * 20000}) + '\nbad\n{"index":2}')
            with patch.object(event_log, "LOG_PATH", path):
                self.assertEqual(event_log.read_events(2), [{"index": 2}])
                self.assertEqual(len(event_log.read_events(3)), 2)
