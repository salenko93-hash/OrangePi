"""Upload limits/cleanup and range semantics used by real browser media elements."""

import io
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from media_io import byte_range, media_type, save_stream


class MediaIOTests(unittest.TestCase):
    def test_single_byte_suffix_and_open_ranges(self):
        for value, expected in [
            ("bytes=0-0", (0, 0)),
            ("bytes=4-", (4, 9)),
            ("bytes=-3", (7, 9)),
            ("bytes=4-99", (4, 9)),
            ("bytes=-99", (0, 9)),
        ]:
            with self.subTest(value=value):
                self.assertEqual(byte_range(value, 10), expected)

    def test_invalid_or_multiple_ranges_are_rejected(self):
        for value in (
            "bytes=10-",
            "bytes=-0",
            "bytes=4-2",
            "bytes=-",
            "bytes=0-1,4-5",
            "items=0-1",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                byte_range(value, 10)

    def test_upload_is_bounded_and_preserves_bytes(self):
        class Bounded(io.BytesIO):
            def read(self, n=-1):
                if n < 0 or n > 65536:
                    raise AssertionError("unbounded upload read")
                return super().read(n)

        raw = b"\x00\x00\x00\x18ftypisom" + b"video-data" * 30000
        with tempfile.TemporaryDirectory() as tmp:
            result = save_stream(tmp, "../clip.mp4", Bounded(raw), len(raw))
            self.assertEqual(result["media_kind"], "video")
            self.assertEqual((Path(tmp) / result["file"]).read_bytes(), raw)
            self.assertEqual(len([p for p in Path(tmp).iterdir() if p.is_file()]), 1)

    def test_failed_upload_removes_partial_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                save_stream(tmp, "clip.webm", io.BytesIO(b"x"), 100)
            self.assertEqual([p for p in Path(tmp).iterdir() if p.is_file()], [])

    def test_limits_and_unsupported_extensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("photo.jpg", "video.mp4", "track.mp3"):
                kind, limit = media_type(name)
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    save_stream(tmp, name, io.BytesIO(b"x"), limit + 1)
            with self.assertRaises(ValueError):
                save_stream(tmp, "bad.exe", io.BytesIO(b"x"), 1)
            self.assertEqual([p for p in Path(tmp).iterdir() if p.is_file()], [])
