"""Install a transparent Xcursor theme for the TV service only."""

import os
from pathlib import Path
import struct
import tempfile

THEME = "lyceumtv-invisible"
THEME_NAMES = (THEME, "default", "left_ptr")
SEARCH_PATH = "usr/local/share/lyceumtv-cursors"
CURSOR_NAMES = (
    "left_ptr",
    "default",
    "arrow",
    "top_left_arrow",
    "pointer",
    "hand1",
    "hand2",
    "text",
    "xterm",
    "ibeam",
    "wait",
    "watch",
    "progress",
    "left_ptr_watch",
    "move",
    "fleur",
    "grab",
    "grabbing",
    "help",
    "question_arrow",
    "crosshair",
    "cross",
    "not-allowed",
    "forbidden",
    "no-drop",
    "copy",
    "alias",
    "context-menu",
    "cell",
    "vertical-text",
    "all-scroll",
    "col-resize",
    "row-resize",
    "n-resize",
    "s-resize",
    "e-resize",
    "w-resize",
    "ne-resize",
    "nw-resize",
    "se-resize",
    "sw-resize",
    "ew-resize",
    "ns-resize",
    "nesw-resize",
    "nwse-resize",
    "size_all",
    "size_hor",
    "size_ver",
    "size_bdiag",
    "size_fdiag",
    "zoom-in",
    "zoom-out",
)


def transparent_cursor():
    # Xcursor header, one image TOC entry, image header, one transparent ARGB pixel.
    return struct.pack(
        "<7I", 0x72756358, 16, 0x10000, 1, 0xFFFD0002, 24, 28
    ) + struct.pack("<10I", 36, 0xFFFD0002, 24, 1, 1, 1, 0, 0, 0, 0)


def write_atomic(path, content):
    fd, temporary = tempfile.mkstemp(prefix=".cursor-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            os.fchmod(stream.fileno(), 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def install(root=Path("/")):
    root = Path(root)
    icons = root / SEARCH_PATH
    dropin = root / "etc/systemd/system/lyceumtv-kiosk.service.d"
    directories = [icons, dropin]
    for theme_name in THEME_NAMES:
        theme = icons / theme_name
        directories.extend((theme, theme / "cursors"))
    for directory in directories:
        if directory.is_symlink():
            raise RuntimeError(
                "Refusing linked configuration directory: " + str(directory)
            )
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o755)
    # Cage 0.2.1 passes NULL as the pointer theme to wlroots, which loads
    # "default" without consulting XCURSOR_THEME. XWayland uses "left_ptr".
    # Both aliases live in this service's private search path, never in the
    # global /usr/share/icons/default theme used by other sessions.
    for theme_name in THEME_NAMES:
        theme = icons / theme_name
        for name in CURSOR_NAMES:
            write_atomic(theme / "cursors" / name, transparent_cursor())
        write_atomic(
            theme / "index.theme",
            b"[Icon Theme]\nName=LyceumTV invisible cursor\nDirectories=cursors\n",
        )
    # Cage inherits these variables from this service, independently of desktops.
    write_atomic(
        dropin / "50-cursor.conf",
        (
            "[Service]\n"
            f"Environment=XCURSOR_THEME={THEME}\n"
            f"Environment=XCURSOR_PATH=/{SEARCH_PATH}\n"
        ).encode(),
    )


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run this installer with sudo.")
    install()
    print("Installed cursor fix v2: private default theme for Cage 0.2.1.")


if __name__ == "__main__":
    main()
