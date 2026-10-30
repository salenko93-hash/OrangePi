"""Check that Cage can decode the installed transparent cursor by theme name."""

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
            for name in cursor.CURSOR_NAMES:
                path = root / "usr/local/share/icons" / cursor.THEME / "cursors" / name
                self.assertEqual(path.read_bytes(), cursor.transparent_cursor())
                self.assertEqual(path.stat().st_mode & 0o777, 0o644)
            self.assertEqual(
                list((root / "etc/systemd/system").iterdir()),
                [root / "etc/systemd/system/lyceumtv-kiosk.service.d"],
            )

    @unittest.skipUnless(
        ctypes.util.find_library("Xcursor"), "native libXcursor unavailable"
    )
    def test_native_theme_lookup_decodes_transparent_pixel(self):
        with tempfile.TemporaryDirectory() as directory:
            cursor.install(Path(directory))
            env = os.environ.copy()
            env["XCURSOR_PATH"] = str(Path(directory) / "usr/local/share/icons")
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
