"""Photo/video selection for the public after-school slideshow."""

from datetime import datetime
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from smart_ops import after_school_slides, normalize


class AfterSchoolSlideshowTests(unittest.TestCase):
    now = datetime(2026, 10, 19, 15, 0)

    def photo(self, name="photo", **changes):
        return {
            "id": name,
            "title": name,
            "media_kind": "image",
            "url": f"/media/{name}.jpg",
            "active": True,
            "after_school_slideshow": True,
            **changes,
        }

    def selected(self, items):
        with patch("smart_ops.load_ops", return_value={"media": items}):
            return after_school_slides(self.now)

    def test_existing_media_is_not_automatically_selected(self):
        self.assertFalse(
            normalize("media", {"url": "/media/old.jpg"})["after_school_slideshow"]
        )
        self.assertFalse(
            normalize(
                "media", {"url": "/media/old.jpg", "after_school_slideshow": "false"}
            )["after_school_slideshow"]
        )

    def test_video_can_be_selected_for_full_length_playback(self):
        item = normalize(
            "media",
            {
                "url": "/media/movie.mp4",
                "media_kind": "video",
                "after_school_slideshow": True,
            },
        )
        self.assertTrue(item["after_school_slideshow"])

    def test_only_active_selected_images_and_videos_are_returned(self):
        result = self.selected(
            [
                self.photo(),
                self.photo("inactive", active=False),
                self.photo("unselected", after_school_slideshow=False),
                self.photo("video", media_kind="video"),
                self.photo("empty", url=""),
                None,
            ]
        )
        self.assertEqual([p["id"] for p in result["items"]], ["photo", "video"])
        self.assertEqual(result["interval_seconds"], 3)

    def test_respects_photo_availability(self):
        result = self.selected(
            [
                self.photo(
                    "available", days=["MONDAY"], start_time="14:00", end_time="16:00"
                ),
                self.photo("expired", valid_to="2026-10-18"),
                self.photo("future", valid_from="2026-10-20"),
                self.photo("early", start_time="16:00"),
                self.photo("late", end_time="14:00"),
                self.photo("wrong-day", days=["TUESDAY"]),
            ]
        )
        self.assertEqual([p["id"] for p in result["items"]], ["available"])

    def test_only_local_media_and_public_https_urls_are_allowed(self):
        urls = [
            "javascript:alert(1)",
            "http://example.com/a.jpg",
            "//example.com/a.jpg",
            "/api/admin/config",
            "https://user:password@example.com/a.jpg",
            "https://[bad",
            "https://example.com/photo.jpg",
        ]
        result = self.selected(
            [self.photo(str(i), url=url) for i, url in enumerate(urls)]
        )
        self.assertEqual([p["url"] for p in result["items"]], [urls[-1]])

    def test_public_payload_is_limited_to_photo_fields(self):
        result = self.selected([self.photo(message="internal note", priority=9)])
        self.assertEqual(set(result["items"][0]), {"id", "url", "kind"})

    def test_groups_photos_before_videos_and_calculates_music_duration(self):
        result = self.selected(
            [
                self.photo("video1", media_kind="video"),
                self.photo("first"),
                self.photo("video2", media_kind="video"),
                self.photo("second"),
            ]
        )
        self.assertEqual(
            [p["id"] for p in result["items"]], ["first", "second", "video1", "video2"]
        )
        self.assertEqual(result["photo_count"], 2)
        self.assertEqual(result["photo_duration_seconds"], 6)

    def test_keeps_upload_order(self):
        result = self.selected(
            [self.photo("first", priority=0), self.photo("second", priority=9)]
        )
        self.assertEqual([p["id"] for p in result["items"]], ["first", "second"])


if __name__ == "__main__":
    unittest.main()
