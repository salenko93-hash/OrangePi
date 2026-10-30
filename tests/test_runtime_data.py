from pathlib import Path
import tempfile
import unittest
from runtime_data import initialize_runtime_data


class RuntimeDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "data/default").mkdir(parents=True)
        for name in (
            "calendar.json",
            "schedule_numerator.json",
            "content_manifest.json",
            "smart_ops.json",
        ):
            (self.root / "data/default" / name).write_text("{}")

    def test_initializes_only_working_bundle(self):
        self.assertTrue(initialize_runtime_data(self.root))
        self.assertEqual(
            {p.name for p in (self.root / "data/current").iterdir()},
            {"calendar.json", "schedule_numerator.json", "content_manifest.json"},
        )

    def test_does_not_replace_or_mix_existing_live_data(self):
        current = self.root / "data/current"
        current.mkdir()
        (current / "calendar.json").write_text('{"custom":true}')
        self.assertFalse(initialize_runtime_data(self.root))
        self.assertEqual(list(p.name for p in current.iterdir()), ["calendar.json"])
        self.assertEqual((current / "calendar.json").read_text(), '{"custom":true}')
