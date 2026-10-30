from pathlib import Path
import hashlib, sys, tempfile, unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from package_validation import SCHEDULES, verify_manifest


class PackageValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manifest = {"schedules": {}}
        for name in sorted(SCHEDULES | {"calendar.json", "content.json"}):
            data = b"{}"
            (self.root / name).write_bytes(data)
            item = {"url": name, "sha256": hashlib.sha256(data).hexdigest()}
            if name in SCHEDULES:
                self.manifest["schedules"][name] = item
            else:
                self.manifest[name[:-5]] = item

    def test_valid_bundle(self):
        verify_manifest(self.manifest, self.root)

    def test_missing_schedule_is_rejected(self):
        self.manifest["schedules"].pop("schedule_numerator.json")
        with self.assertRaises(ValueError):
            verify_manifest(self.manifest, self.root)

    def test_modified_data_is_rejected(self):
        (self.root / "calendar.json").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            verify_manifest(self.manifest, self.root)

    def test_external_path_is_rejected(self):
        self.manifest["content"]["url"] = "../content.json"
        with self.assertRaises(ValueError):
            verify_manifest(self.manifest, self.root)


if __name__ == "__main__":
    unittest.main()
