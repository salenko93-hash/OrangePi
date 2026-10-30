import json
import os
from pathlib import Path
import tempfile
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch
from json_cache import load_json, clear_json_cache


class JsonCacheTests(unittest.TestCase):
    def setUp(self):
        clear_json_cache()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "data.json"
        self.path.write_text('{"items":[{"value":1}]}')

    def test_unchanged_file_is_parsed_once(self):
        original = Path.read_text
        with patch.object(
            Path, "read_text", autospec=True, side_effect=original
        ) as read:
            for _ in range(10):
                self.assertEqual(load_json(self.path)["items"][0]["value"], 1)
            self.assertEqual(read.call_count, 1)

    def test_atomic_replacement_invalidates_even_with_same_mtime(self):
        old = self.path.stat()
        load_json(self.path)
        other = self.path.with_suffix(".tmp")
        other.write_text('{"items":[{"value":2}]}')
        os.utime(other, ns=(old.st_atime_ns, old.st_mtime_ns))
        os.replace(other, self.path)
        self.assertEqual(load_json(self.path)["items"][0]["value"], 2)

    def test_returns_independent_nested_objects(self):
        value = load_json(self.path)
        value["items"][0]["value"] = 99
        self.assertEqual(load_json(self.path)["items"][0]["value"], 1)

    def test_broken_or_deleted_file_does_not_return_stale_data(self):
        load_json(self.path)
        self.path.write_text("{bad")
        with self.assertRaises(json.JSONDecodeError):
            load_json(self.path)
        self.path.unlink()
        with self.assertRaises(FileNotFoundError):
            load_json(self.path)
        self.path.write_text('{"fixed":true}')
        self.assertTrue(load_json(self.path)["fixed"])

    def test_concurrent_reads_are_independent(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            values = list(pool.map(lambda _: load_json(self.path), range(40)))
        values[0]["items"].clear()
        self.assertEqual(len(values[1]["items"]), 1)
