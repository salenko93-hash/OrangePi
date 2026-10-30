"""Install a transparent Xcursor theme for the TV service only."""

import os
from pathlib import Path
import struct
import tempfile

THEME = "lyceumtv-invisible"
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
    icons = root / "usr/local/share/icons"
    theme = icons / THEME
    dropin = root / "etc/systemd/system/lyceumtv-kiosk.service.d"
    for directory in (icons, theme, theme / "cursors", dropin):
        if directory.is_symlink():
            raise RuntimeError(
                "Refusing linked configuration directory: " + str(directory)
            )
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o755)
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
            "Environment=XCURSOR_PATH=/usr/local/share/icons:/usr/share/icons:/usr/share/pixmaps\n"
        ).encode(),
    )


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run this installer with sudo.")
    install()
    print("Installed invisible cursor theme for lyceumtv-kiosk.service only.")


if __name__ == "__main__":
    main()
