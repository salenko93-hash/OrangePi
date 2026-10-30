"""Read boot/display state without changing outputs, services or configuration."""

import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import sys
from urllib.request import urlopen

ENV_KEYS = (
    "XCURSOR_THEME",
    "XCURSOR_PATH",
    "WLR_NO_HARDWARE_CURSORS",
    "XDG_RUNTIME_DIR",
    "WAYLAND_DISPLAY",
    "GDK_BACKEND",
    "GSK_RENDERER",
    "WEBKIT_DISABLE_DMABUF_RENDERER",
    "LIBSEAT_BACKEND",
)

# Load cursor assets as the actual kiosk UID, without opening a Wayland display
# or creating a GUI. This distinguishes a transparent theme from a fallback arrow.
NATIVE_CURSOR_PROBE = """import ctypes as c, ctypes.util, json, os, sys
library = sys.argv[1] if len(sys.argv) > 1 else (ctypes.util.find_library("wlroots-0.19") or ctypes.util.find_library("wlroots-0.18"))
if not library:
    print(json.dumps({"available": False, "reason": "wlroots cursor library not found"}))
    raise SystemExit(0)
class Image(c.Structure):
    _fields_ = [(n, c.c_uint32) for n in ("width", "height", "hotspot_x", "hotspot_y", "delay")] + [("buffer", c.POINTER(c.c_uint8))]
class Cursor(c.Structure):
    _fields_ = [("image_count", c.c_uint), ("images", c.POINTER(c.POINTER(Image))), ("name", c.c_char_p), ("total_delay", c.c_uint32)]
lib = c.CDLL(library)
lib.wlr_xcursor_theme_load.argtypes = [c.c_char_p, c.c_int]
lib.wlr_xcursor_theme_load.restype = c.c_void_p
lib.wlr_xcursor_theme_get_cursor.argtypes = [c.c_void_p, c.c_char_p]
lib.wlr_xcursor_theme_get_cursor.restype = c.POINTER(Cursor)
lib.wlr_xcursor_theme_destroy.argtypes = [c.c_void_p]
result = {"available": True, "uid": os.geteuid(), "library": library, "cursors": []}
for theme_name in (None, b"default", b"lyceumtv-invisible"):
    theme = lib.wlr_xcursor_theme_load(theme_name, 24)
    if not theme:
        result["cursors"].append({"theme": str(theme_name), "loaded": False})
        continue
    try:
        for name in (b"left_ptr", b"default"):
            pointer = lib.wlr_xcursor_theme_get_cursor(theme, name)
            item = {"theme": str(theme_name), "name": name.decode(), "loaded": bool(pointer)}
            if pointer and pointer.contents.image_count:
                image = pointer.contents.images[0].contents
                if not (0 < image.width <= 4096 and 0 < image.height <= 4096):
                    raise RuntimeError("Unexpected cursor image dimensions")
                item.update(width=image.width, height=image.height, visible_alpha=any(image.buffer[i] for i in range(3, image.width * image.height * 4, 4)))
            result["cursors"].append(item)
    finally:
        lib.wlr_xcursor_theme_destroy(theme)
print(json.dumps(result, indent=2))
"""


def read(path):
    try:
        return Path(path).read_text(errors="replace").strip()
    except OSError as error:
        return "unavailable: " + str(error)


def filtered_environment(raw):
    entries = (item.partition(b"=") for item in raw.split(b"\0"))
    return {
        key.decode(): value.decode(errors="replace")
        for key, separator, value in entries
        if separator and key.decode(errors="replace") in ENV_KEYS
    }


def processes(uid, proc=Path("/proc")):
    records = []
    for directory in sorted(proc.iterdir()):
        if not directory.name.isdigit():
            continue
        try:
            status = (directory / "status").read_text()
            identity = re.search(r"^Uid:\s+(\d+)\s+(\d+)", status, re.M)
            # /proc inode ownership can become root after privilege changes;
            # use the process's effective UID rather than the directory owner.
            if not identity or int(identity.group(2)) != uid:
                continue
            comm = (directory / "comm").read_text().strip()
            # Inspect argv only to identify our host, never include argv in output.
            is_host = b"kiosk_browser.py" in (directory / "cmdline").read_bytes()
            if (
                comm not in ("cage", "Xwayland", "WebKitWebProces", "WebKitWebProcess")
                and not is_host
            ):
                continue
            record = {"pid": int(directory.name), "comm": comm}
            record["environment"] = filtered_environment(
                (directory / "environ").read_bytes()
            )
            record["status"] = [
                line
                for line in status.splitlines()
                if re.match(
                    r"^(PPid|Uid|CapInh|CapPrm|CapEff|CapAmb|NoNewPrivs):", line
                )
            ]
            record["cgroup"] = read(directory / "cgroup")
            records.append(record)
        except OSError:
            continue  # Process may exit during a snapshot.
    return records


def command(argv, *, label=None, **kwargs):
    print("COMMAND:", label or " ".join(argv), flush=True)
    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=10, **kwargs
        )
        print(result.stdout[-40000:])
        if result.stderr:
            print(result.stderr[-4000:])
        print("exit:", result.returncode, flush=True)
    except (OSError, subprocess.SubprocessError) as error:
        print("unavailable:", error, flush=True)


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run this diagnostic using sudo.")
    print("LyceumTV read-only display diagnostic v2", flush=True)
    command(["date", "--iso-8601=seconds"])
    command(["uptime"])
    command(["uname", "-a"])
    try:
        with urlopen("http://127.0.0.1:8080/api/health", timeout=3) as response:
            health = json.load(response)
        print(
            "API:",
            json.dumps({key: health.get(key) for key in ("ok", "version", "service")}),
        )
    except (OSError, ValueError) as error:
        print("API unavailable:", error)
    command(
        [
            "systemctl",
            "show",
            "--no-pager",
            "lyceumtv-kiosk.service",
            "-p",
            "ActiveState",
            "-p",
            "SubState",
            "-p",
            "MainPID",
            "-p",
            "NRestarts",
            "-p",
            "ExecMainStatus",
            "-p",
            "FragmentPath",
            "-p",
            "DropInPaths",
        ]
    )
    launcher = Path("/usr/local/lib/lyceumtv/launch-kiosk.sh")
    try:
        source = launcher.read_bytes()
        print("launcher SHA256:", hashlib.sha256(source).hexdigest())
        print("launcher cursor block:", b"BEGIN LyceumTV cursor environment" in source)
        print("launcher single output:", b"/usr/bin/cage -m last --" in source)
    except OSError as error:
        print("launcher unavailable:", error)
    for name, markers in (
        (
            "kiosk_browser.py",
            {
                "window_cursor_hidden": b'window.set_cursor_from_name("none")',
                "gtk_cursor_theme": b"gtk-cursor-theme-name",
            },
        ),
        ("display_mode.py", {"native_mode_default": b"if not args.prefer_720p:"}),
    ):
        try:
            raw = (launcher.parent / name).read_bytes()
            print(
                name,
                "SHA256:",
                hashlib.sha256(raw).hexdigest(),
                "features:",
                {key: value in raw for key, value in markers.items()},
            )
        except OSError as error:
            print(name, "unavailable:", error)

    print("=== DRM CONNECTORS ===")
    for connector in sorted(Path("/sys/class/drm").glob("card*-*")):
        if not (connector / "status").exists():
            continue
        print(connector.name)
        for name in ("status", "enabled", "dpms", "modes"):
            print(name + ":", read(connector / name))
        try:
            edid = (connector / "edid").read_bytes()
            print("EDID bytes:", len(edid), "SHA256:", hashlib.sha256(edid).hexdigest())
        except OSError as error:
            print("EDID unavailable:", error)
    print("=== DRM PLANE / CRTC STATE ===")
    states = list(Path("/sys/kernel/debug/dri").glob("*/state"))
    if not states:
        print("DRM debug state unavailable; debugfs will not be mounted by this check.")
    for path in states:
        print(str(path), read(path)[:20000])

    account = pwd.getpwnam("lyceumtv-kiosk")
    if account.pw_uid == 0:
        raise SystemExit("Refusing unexpected kiosk UID 0")
    snapshot = processes(account.pw_uid)
    print("=== ACTUAL CAGE / BROWSER PROCESSES (selected fields only) ===")
    print(json.dumps(snapshot, ensure_ascii=False, indent=2), flush=True)
    cage_environment = next(
        (item["environment"] for item in snapshot if item["comm"] == "cage"), {}
    )
    if cage_environment:
        env = {"PATH": "/usr/bin:/bin", "HOME": account.pw_dir, **cage_environment}
        print("=== ACTUAL KIOSK UID CURSOR ASSET DECODE ===")
        command(
            [sys.executable, "-I", "-c", NATIVE_CURSOR_PROBE],
            label="wlroots cursor decoding as kiosk UID; no GUI or display change",
            user=account.pw_uid,
            group=account.pw_gid,
            extra_groups=os.getgrouplist(account.pw_name, account.pw_gid),
            env=env,
            cwd="/",
        )
    display = next(
        (
            item["environment"]
            for item in snapshot
            if item["environment"].get("WAYLAND_DISPLAY")
        ),
        None,
    )
    if display:
        env = {
            "PATH": "/usr/bin:/bin",
            "XDG_RUNTIME_DIR": display.get(
                "XDG_RUNTIME_DIR", f"/run/user/{account.pw_uid}"
            ),
            "WAYLAND_DISPLAY": display["WAYLAND_DISPLAY"],
        }
        command(
            ["/usr/bin/wlr-randr", "--json"],
            user=account.pw_uid,
            group=account.pw_gid,
            extra_groups=os.getgrouplist(account.pw_name, account.pw_gid),
            env=env,
            cwd="/",
        )
    else:
        print("No running browser Wayland environment found; output query skipped.")
    print("=== CURSOR THEME FILES ===")
    for name in ("default", "left_ptr", "lyceumtv-invisible"):
        path = Path("/usr/local/share/lyceumtv-cursors") / name / "cursors/left_ptr"
        try:
            raw = path.read_bytes()
            print(
                name,
                "bytes:",
                len(raw),
                "mode:",
                stat.S_IMODE(path.stat().st_mode),
                "SHA256:",
                hashlib.sha256(raw).hexdigest(),
            )
        except OSError as error:
            print(name, "unavailable:", error)
    print("=== FIRST BOOT KIOSK LOG ===", flush=True)
    command(
        ["journalctl", "-b", "-u", "lyceumtv-kiosk.service", "--no-pager", "-n", "100"]
    )
    command(["journalctl", "-b", f"_UID={account.pw_uid}", "--no-pager", "-n", "100"])
    command(
        [
            "journalctl",
            "-b",
            f"_UID={account.pw_uid}",
            "--no-pager",
            "--grep=GTK cursor:|no startup resolution change|HDMI low-memory mode:|disconnected|connected",
            "-n",
            "60",
        ]
    )
    command(
        [
            "journalctl",
            "-b",
            "-k",
            "--no-pager",
            "--grep=drm|hdmi|sun4i|sun8i|lima",
            "-n",
            "80",
        ]
    )
    print(
        "DIAGNOSTIC COMPLETE. No services, display modes or settings were changed.",
        flush=True,
    )


if __name__ == "__main__":
    main()
