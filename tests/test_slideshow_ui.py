"""Slideshow UI invariants."""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SlideshowUiTests(unittest.TestCase):
    def text(self, rel):
        return (ROOT / rel).read_text(encoding="utf-8-sig")

    def test_tv_slideshow_contains_configured_title_and_media(self):
        html = self.text("public/index.html")
        self.assertIn('id="slideshowTitle"', html)
        self.assertNotIn('id="afterSchoolAnnouncement"', html)
        self.assertNotIn('id="afterSchoolPhotoTitle"', html)
        self.assertNotIn('id="afterSchoolPhotoCount"', html)
        self.assertNotIn("СЬОГОДНІ У ЛІЦЕЇ", html)

    def test_slideshow_js_does_not_render_file_title_or_counter(self):
        js = self.text("public/js/slideshow.js")
        self.assertNotIn("afterSchoolPhotoTitle", js)
        self.assertNotIn("afterSchoolPhotoCount", js)
        self.assertNotIn("photo.title", js)

    def test_admin_has_slideshow_title_setting(self):
        html = self.text("public/admin.html")
        js = self.text("public/js/admin.js")
        self.assertIn('name="slideshow_title"', html)
        self.assertIn('"slideshowSettings"', js)

    def test_preview_has_no_announcement_editor(self):
        html = self.text("public/slideshow-preview.html")
        js = self.text("public/js/slideshow-preview.js")
        self.assertNotIn("previewText", html)
        self.assertNotIn("afterSchoolAnnouncement", html)
        self.assertNotIn("previewText", js)


if __name__ == "__main__":
    unittest.main()
