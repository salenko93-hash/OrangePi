"""Check decoding and Cage's actual NULL/default-theme lookup in wlroots."""

import ctypes
import ctypes.util
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "hide_cursor", ROOT / "scripts/hide_cursor.py"
)
cursor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cursor)


class CursorThemeTests(unittest.TestCase):
    def test_theme_is_readable_idempotent_and_scoped_to_kiosk(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cursor.install(root)
            cursor.install(root)
            for theme in cursor.THEME_NAMES:
                for name in cursor.CURSOR_NAMES:
                    path = root / cursor.SEARCH_PATH / theme / "cursors" / name
                    self.assertEqual(path.read_bytes(), cursor.transparent_cursor())
                    self.assertEqual(path.stat().st_mode & 0o777, 0o644)
            self.assertEqual(
                list((root / "etc/systemd/system").iterdir()),
                [root / "etc/systemd/system/lyceumtv-kiosk.service.d"],
            )
            self.assertFalse((root / "usr/share/icons").exists())
            config = (
                root / "etc/systemd/system/lyceumtv-kiosk.service.d/50-cursor.conf"
            ).read_text()
            self.assertIn(
                "Environment=XCURSOR_PATH=/" + cursor.SEARCH_PATH + "\n", config
            )

    @unittest.skipUnless(
        ctypes.util.find_library("Xcursor"), "native libXcursor unavailable"
    )
    def test_native_theme_lookup_decodes_transparent_pixel(self):
        with tempfile.TemporaryDirectory() as directory:
            cursor.install(Path(directory))
            env = os.environ.copy()
            env["XCURSOR_PATH"] = str(Path(directory) / cursor.SEARCH_PATH)
            # A fresh process avoids libXcursor's cached search path.
            probe = """import ctypes, ctypes.util
lib = ctypes.CDLL(ctypes.util.find_library("Xcursor"))
class Image(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint32) for n in ("version", "size", "width", "height", "xhot", "yhot", "delay")] + [("pixels", ctypes.POINTER(ctypes.c_uint32))]
lib.XcursorLibraryLoadImage.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
lib.XcursorLibraryLoadImage.restype = ctypes.POINTER(Image)
lib.XcursorImageDestroy.argtypes = [ctypes.POINTER(Image)]
for name in (b"left_ptr", b"default", b"pointer", b"text", b"wait"):
    for size in (16, 24, 32, 48):
        image = lib.XcursorLibraryLoadImage(name, b"lyceumtv-invisible", size)
        assert image, (name, size)
        assert (image.contents.width, image.contents.height, image.contents.pixels[0]) == (1, 1, 0)
        lib.XcursorImageDestroy(image)
"""
            subprocess.run([sys.executable, "-c", probe], env=env, check=True)

    @unittest.skipUnless(
        os.environ.get("LYCEUMTV_TEST_WLROOTS_LIBRARY")
        or ctypes.util.find_library("wlroots-0.18"),
        "optional native wlroots 0.18 library unavailable",
    )
    def test_native_wlroots_default_lookup_and_previous_failure(self):
        library = os.environ.get(
            "LYCEUMTV_TEST_WLROOTS_LIBRARY"
        ) or ctypes.util.find_library("wlroots-0.18")
        probe = """import ctypes as c, sys
class Image(c.Structure):
    _fields_ = [(n, c.c_uint32) for n in ("width", "height", "hotspot_x", "hotspot_y", "delay")] + [("buffer", c.POINTER(c.c_uint8))]
class Cursor(c.Structure):
    _fields_ = [("image_count", c.c_uint), ("images", c.POINTER(c.POINTER(Image))), ("name", c.c_char_p), ("total_delay", c.c_uint32)]
lib = c.CDLL(sys.argv[1])
lib.wlr_xcursor_theme_load.argtypes = [c.c_char_p, c.c_int]
lib.wlr_xcursor_theme_load.restype = c.c_void_p
lib.wlr_xcursor_theme_get_cursor.argtypes = [c.c_void_p, c.c_char_p]
lib.wlr_xcursor_theme_get_cursor.restype = c.POINTER(Cursor)
lib.wlr_xcursor_theme_destroy.argtypes = [c.c_void_p]
fixed = sys.argv[2] == "fixed"
for theme_name in (None, b"default", b"left_ptr", b"lyceumtv-invisible"):
    for size in (16, 24, 32, 48):
        theme = lib.wlr_xcursor_theme_load(theme_name, size)
        assert theme
        for name in (b"left_ptr", b"default", b"pointer", b"text", b"wait"):
            p = lib.wlr_xcursor_theme_get_cursor(theme, name)
            if not fixed and theme_name != b"lyceumtv-invisible" and name != b"left_ptr":
                continue  # Built-in fallback need not contain every alias.
            assert p, (theme_name, name, size)
            image = p.contents.images[0].contents
            opaque = any(image.buffer[i] for i in range(3, image.width * image.height * 4, 4))
            expected_hidden = fixed or theme_name == b"lyceumtv-invisible"
            assert opaque != expected_hidden, (theme_name, name, size, opaque)
            if expected_hidden:
                assert (image.width, image.height) == (1, 1)
        lib.wlr_xcursor_theme_destroy(theme)
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cursor.install(root)
            # Reproduce v1: only the named theme existed; XCURSOR_THEME was set.
            old = root / "old-layout"
            old.mkdir()
            (old / cursor.THEME).symlink_to(root / cursor.SEARCH_PATH / cursor.THEME)
            for path, mode in ((old, "old"), (root / cursor.SEARCH_PATH, "fixed")):
                env = os.environ.copy()
                env.update(XCURSOR_PATH=str(path), XCURSOR_THEME=cursor.THEME)
                subprocess.run(
                    [sys.executable, "-c", probe, library, mode], env=env, check=True
                )
