param(
    [string]$BoardHost = "192.168.0.160",
    [string]$BoardUser = "admin"
)
$ErrorActionPreference = "Stop"
$parsedIP = $null
if (-not [System.Net.IPAddress]::TryParse($BoardHost, [ref]$parsedIP) -or $parsedIP.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) { throw "BoardHost must be an IPv4 address." }
if ($BoardUser -notmatch '^[a-z_][a-z0-9_-]{0,31}$') { throw "Invalid Linux username." }
foreach ($cmd in @("ssh", "scp")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "Windows OpenSSH Client is required." }
}
Write-Host "Repairing kiosk 3.7.4 (Cage pointer refresh after page load) on ${BoardUser}@${BoardHost}..."
$remoteCode = @'
set -eu
sudo -v
new_host=""
new_mode=""
trap 'if [ -n "$new_host" ]; then sudo rm -f -- "$new_host"; fi; if [ -n "$new_mode" ]; then sudo rm -f -- "$new_mode"; fi; rm -f -- "$0"; sudo systemctl start lyceumtv-watchdog.timer' EXIT
sudo systemctl stop lyceumtv-watchdog.timer lyceumtv-watchdog.service lyceumtv-kiosk.service
sudo install -d -o root -g root -m 755 /etc/systemd/system/lyceumtv-kiosk.service.d
sudo tee /etc/systemd/system/lyceumtv-kiosk.service.d/40-lyceumtv-capabilities.conf >/dev/null <<'UNIT'
[Service]
NoNewPrivileges=true
AmbientCapabilities=
UNIT
sudo /usr/bin/python3 -I - <<'PYPROFILE'
"""Prepare each private kiosk directory, including parents, without following links."""

import os
from pathlib import Path
import sys


def prepare_profile(home, uid, gid):
    home = Path(home)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptors = {"": os.open(home, flags)}
    try:
        for relative in (
            "",
            ".cache",
            ".cache/lyceumtv-webkit",
            ".local",
            ".local/share",
            ".local/share/lyceumtv-webkit",
        ):
            if relative:
                parent, _, name = relative.rpartition("/")
                parent_fd = descriptors[parent]
                try:
                    os.mkdir(name, mode=0o700, dir_fd=parent_fd)
                except FileExistsError:
                    pass
                descriptors[relative] = os.open(name, flags, dir_fd=parent_fd)
            descriptor = descriptors[relative]
            os.fchown(descriptor, uid, gid)
            os.fchmod(descriptor, 0o700)
    finally:
        for descriptor in reversed(list(descriptors.values())):
            os.close(descriptor)

import pwd
account = pwd.getpwnam("lyceumtv-kiosk")
if account.pw_uid == 0 or account.pw_dir != "/var/lib/lyceumtv-kiosk":
    raise SystemExit("Refusing unexpected kiosk account/home directory")
prepare_profile(account.pw_dir, account.pw_uid, account.pw_gid)
PYPROFILE
sudo /usr/bin/python3 -I - <<'PYCURSOR'
"""Install a transparent Xcursor theme for the TV service only."""

import os
from pathlib import Path
import struct
import stat
import tempfile

THEME = "lyceumtv-invisible"
THEME_NAMES = (THEME, "default", "left_ptr")
SEARCH_PATH = "usr/local/share/lyceumtv-cursors"
BLOCK_BEGIN = "# BEGIN LyceumTV cursor environment"
BLOCK_END = "# END LyceumTV cursor environment"
LAUNCHER_BLOCK = f"""{BLOCK_BEGIN}
export XCURSOR_THEME={THEME}
export XCURSOR_PATH=/{SEARCH_PATH}
export WLR_NO_HARDWARE_CURSORS=1
echo "TV cursor: theme=$XCURSOR_THEME path=$XCURSOR_PATH software=$WLR_NO_HARDWARE_CURSORS"
{BLOCK_END}
"""
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


def write_atomic(path, content, mode=0o644):
    fd, temporary = tempfile.mkstemp(prefix=".cursor-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            os.fchmod(stream.fileno(), mode)
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
            "Environment=WLR_NO_HARDWARE_CURSORS=1\n"
        ).encode(),
    )


def configure_launcher(path):
    """Set the cursor environment before Cage even without inherited settings."""
    path = Path(path)
    if not stat.S_ISREG(path.lstat().st_mode):
        raise RuntimeError("Refusing a linked/non-regular kiosk launcher")
    original = path.read_text()
    source = original
    if BLOCK_BEGIN in source or BLOCK_END in source:
        if source.count(BLOCK_BEGIN) != 1 or source.count(BLOCK_END) != 1:
            raise RuntimeError("Unexpected cursor block in the kiosk launcher")
        before, block = source.split(BLOCK_BEGIN, 1)
        if BLOCK_END not in block:
            raise RuntimeError("Incomplete cursor block in the kiosk launcher")
        source = before.rstrip("\n") + "\n" + block.split(BLOCK_END, 1)[1].lstrip("\n")
    anchor = "set -Eeuo pipefail\n"
    if (
        not source.startswith("#!")
        or anchor not in source
        or "/usr/bin/cage" not in source
    ):
        raise RuntimeError("Unrecognized kiosk launcher; leaving it unchanged")
    before, after = source.split(anchor, 1)
    updated = before + anchor + "\n" + LAUNCHER_BLOCK + "\n" + after.lstrip("\n")
    # Canonical and previously patched launchers converge without appending blocks.
    if updated != original:
        backup = path.with_name(path.name + ".before-cursor-v3")
        if not backup.exists():
            write_atomic(backup, original.encode(), mode=0o755)
        write_atomic(path, updated.encode(), mode=0o755)


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run this installer with sudo.")
    install()
    launcher = Path("/usr/local/lib/lyceumtv/launch-kiosk.sh")
    if launcher.lstat().st_uid != 0:
        raise SystemExit("Refusing a kiosk launcher not owned by root")
    configure_launcher(launcher)
    print("Installed cursor fix v3: startup environment and software cursor.")


if __name__ == "__main__":
    main()

PYCURSOR
sudo sed -i.before-single-output 's|/usr/bin/cage --|/usr/bin/cage -m last --|' /usr/local/lib/lyceumtv/launch-kiosk.sh
if loginctl show-user --no-pager lyceumtv-kiosk >/dev/null 2>&1; then
  sudo loginctl terminate-user lyceumtv-kiosk
fi
sudo test -d /usr/local/lib/lyceumtv
if [ ! -e /usr/local/lib/lyceumtv/kiosk_browser.py.before-3.7.4 ]; then
  sudo cp -p /usr/local/lib/lyceumtv/kiosk_browser.py /usr/local/lib/lyceumtv/kiosk_browser.py.before-3.7.4
fi
new_mode=$(sudo mktemp /usr/local/lib/lyceumtv/.display-mode-XXXXXX)
sudo tee "$new_mode" >/dev/null <<'PYDISPLAY'
"""Preserve the TV's preferred mode; 720p is an explicit opt-in."""

import argparse
import json
import subprocess


def choose_mode(outputs):
    for output in outputs:
        if not isinstance(output, dict) or not output.get("enabled"):
            continue
        name = output.get("name", "")
        if not name.startswith("HDMI"):
            continue
        modes = [
            mode
            for mode in output.get("modes", [])
            if mode.get("width") == 1280
            and mode.get("height") == 720
            and 49 <= float(mode.get("refresh", 0)) <= 61
        ]
        if modes:
            mode = min(modes, key=lambda m: abs(float(m["refresh"]) - 60))
            return name, f"1280x720@{float(mode['refresh']):.6f}Hz"
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prefer-720p", action="store_true", help="Opt in to an advertised 720p mode"
    )
    args = parser.parse_args(argv)
    if not args.prefer_720p:
        # Sharp HDMI dropped/reconnected twice after our startup 720p modeset.
        # Let Cage keep the EDID preferred mode instead of renegotiating it.
        print(
            "Keeping the TV preferred HDMI mode; no startup resolution change.",
            flush=True,
        )
        return
    try:
        result = subprocess.run(
            ["/usr/bin/wlr-randr", "--json"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        selected = choose_mode(json.loads(result.stdout))
        if selected:
            subprocess.run(
                ["/usr/bin/wlr-randr", "--output", selected[0], "--mode", selected[1]],
                timeout=5,
                check=True,
            )
            print("HDMI low-memory mode:", *selected, flush=True)
        else:
            print(
                "Keeping native display mode: no advertised HDMI 720p mode.", flush=True
            )
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        subprocess.SubprocessError,
    ) as error:
        print("Keeping native display mode:", error, flush=True)


if __name__ == "__main__":
    main()

PYDISPLAY
sudo chown root:root "$new_mode"
sudo chmod 644 "$new_mode"
if [ ! -e /usr/local/lib/lyceumtv/display_mode.py.before-native-mode ]; then
  sudo cp -p /usr/local/lib/lyceumtv/display_mode.py /usr/local/lib/lyceumtv/display_mode.py.before-native-mode
fi
sudo mv -f -- "$new_mode" /usr/local/lib/lyceumtv/display_mode.py
new_mode=""
new_host=$(sudo mktemp /usr/local/lib/lyceumtv/.kiosk-browser-XXXXXX)
sudo tee "$new_host" >/dev/null <<'PYHOST'
"""Small GTK4/WebKitGTK TV host for Orange Pi PC; no desktop or Snap browser."""

import argparse
import ctypes
import json
import os
from pathlib import Path
import socket
import struct
import sys
import time
import traceback
from urllib.parse import urlsplit

TV_URL = "http://127.0.0.1:8080/?screen=main-hall&lite=1"


def browser_security_state():
    keys = {"CapInh", "CapPrm", "CapEff", "CapAmb", "NoNewPrivs"}
    return {
        key: value.strip()
        for line in Path("/proc/self/status").read_text().splitlines()
        for key, separator, value in [line.partition(":")]
        if separator and key in keys
    }


def drop_browser_privileges():
    """Drop existing permitted caps too: no_new_privs alone prevents only gains."""

    class Header(ctypes.Structure):
        _fields_ = [("version", ctypes.c_uint32), ("pid", ctypes.c_int32)]

    class Data(ctypes.Structure):
        _fields_ = [
            ("effective", ctypes.c_uint32),
            ("permitted", ctypes.c_uint32),
            ("inheritable", ctypes.c_uint32),
        ]

    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [ctypes.c_int, *([ctypes.c_ulong] * 4)]
    libc.prctl.restype = ctypes.c_int
    libc.capset.argtypes = [ctypes.POINTER(Header), ctypes.POINTER(Data)]
    libc.capset.restype = ctypes.c_int

    def checked(result, operation):
        if result != 0:
            raise OSError(ctypes.get_errno(), operation)

    # PR_SET_NO_NEW_PRIVS, Linux capability ABI v3, PR_CAP_AMBIENT_CLEAR_ALL.
    checked(libc.prctl(38, 1, 0, 0, 0), "Cannot set no_new_privs")
    header, empty = Header(0x20080522, 0), (Data * 2)()
    checked(
        libc.capset(ctypes.byref(header), empty), "Cannot drop browser capabilities"
    )
    checked(libc.prctl(47, 4, 0, 0, 0), "Cannot clear ambient capabilities")
    state = browser_security_state()
    if state.get("NoNewPrivs") != "1" or any(
        int(state.get(key, "-1"), 16) != 0
        for key in ("CapInh", "CapPrm", "CapEff", "CapAmb")
    ):
        raise RuntimeError(
            "Browser privilege drop could not be verified: " + str(state)
        )
    return state


def allowed_navigation(uri):
    """The TV host cannot become a file browser or an administrative browser."""
    try:
        parsed = urlsplit(uri)
        return (
            parsed.scheme == "http"
            and parsed.hostname == "127.0.0.1"
            and parsed.port == 8080
            and not parsed.username
            and not parsed.password
            and parsed.path in {"/", "/slideshow-preview"}
        )
    except ValueError:
        return False


def load_bindings():
    # Dedicated TV does not provide an accessibility session bus.
    os.environ.setdefault("GTK_A11Y", "none")
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("WebKit", "6.0")
    from gi.repository import Gio, GLib, Gtk, WebKit

    return Gio, GLib, Gtk, WebKit


def make_settings(WebKit):
    return WebKit.Settings(
        enable_developer_extras=False,
        media_playback_requires_user_gesture=False,
        enable_page_cache=False,
        hardware_acceleration_policy=WebKit.HardwareAccelerationPolicy.NEVER,
    )


def configure_gtk_cursor(Gtk):
    # Cage and GTK can load different cursor themes. Set the client theme too,
    # so a WebKit request for a standard pointer still resolves to transparency.
    settings = Gtk.Settings.get_default()
    if settings is not None:
        settings.set_property("gtk-cursor-theme-name", "lyceumtv-invisible")


def refresh_seat_cursor():
    """Refresh Cage's seat after page load, without clicks or pointer movement.

    A temporary wlr virtual pointer emits zero relative motion, then is removed.
    Cage's pointer-destroy handler unsets its cursor image when no mouse remains.
    This uses the compositor socket as the kiosk user; no uinput/root is needed.
    """
    if os.geteuid() == 0:
        raise RuntimeError("Do not refresh the kiosk pointer as root")
    runtime = Path(os.environ["XDG_RUNTIME_DIR"]).resolve()
    name = os.environ.get("WAYLAND_DISPLAY", "wayland-0")
    path = Path(name) if os.path.isabs(name) else runtime / name
    if path.parent.resolve() != runtime or path.stat().st_uid != os.geteuid():
        raise RuntimeError("Unexpected compositor socket owner or location")
    deadline = time.monotonic() + 2
    pending = bytearray()
    globals_by_name = {}

    def words(*values):
        return struct.pack("=" + "I" * len(values), *values)

    def string(value):
        raw = value.encode("ascii") + b"\0"
        return words(len(raw)) + raw + b"\0" * (-len(raw) % 4)

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(2)
        connection.connect(str(path))

        def send(object_id, opcode, body=b""):
            connection.sendall(
                words(object_id, ((8 + len(body)) << 16) | opcode) + body
            )

        def roundtrip(callback_id):
            send(1, 0, words(callback_id))  # wl_display.sync
            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Compositor pointer refresh timed out")
                if len(pending) >= 8:
                    object_id, header = struct.unpack("=II", pending[:8])
                    size, opcode = header >> 16, header & 0xFFFF
                    if size < 8 or size > 65532 or size % 4:
                        raise RuntimeError("Invalid Wayland event size")
                    if len(pending) >= size:
                        body = bytes(pending[8:size])
                        del pending[:size]
                        if object_id == 1 and opcode == 0:
                            raise RuntimeError("Compositor rejected pointer refresh")
                        if object_id == 2 and opcode == 0:
                            global_id, length = struct.unpack("=II", body[:8])
                            offset = 8 + ((length + 3) & ~3)
                            if not (1 <= length <= 1024 and len(body) >= offset + 4):
                                raise RuntimeError("Invalid Wayland global event")
                            interface = body[8 : 8 + length - 1].decode("ascii")
                            globals_by_name[interface] = global_id
                        if object_id == callback_id and opcode == 0:
                            return
                        continue
                connection.settimeout(max(0.01, deadline - time.monotonic()))
                packet = connection.recv(65536)
                if not packet:
                    raise RuntimeError("Compositor disconnected during pointer refresh")
                pending.extend(packet)

        send(1, 1, words(2))  # wl_display.get_registry
        roundtrip(3)
        interface = "zwlr_virtual_pointer_manager_v1"
        if interface not in globals_by_name:
            return False
        send(2, 0, words(globals_by_name[interface]) + string(interface) + words(1, 4))
        send(4, 0, words(0, 5))  # create_virtual_pointer, default seat
        roundtrip(6)
        send(5, 0, words(int(time.monotonic() * 1000) & 0xFFFFFFFF, 0, 0))
        send(5, 4)  # frame; no button/scroll/absolute-motion requests
        send(5, 8)  # destroy virtual pointer; Cage refreshes seat capabilities
        send(4, 1)  # destroy manager binding
        roundtrip(7)
    return True


def present_kiosk_window(window):
    # Cage fills its output itself. Calling fullscreen before the initial commit
    # hits an uninitialized xdg_surface in Cage 0.2.1 / wlroots 0.19.
    window.set_decorated(False)
    window.set_default_size(1280, 720)
    window.set_cursor_from_name("none")
    window.present()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Check GI packages; no display required"
    )
    parser.add_argument(
        "--check-privileges",
        action="store_true",
        help="Drop/check own Linux caps; no GUI",
    )
    args = parser.parse_args(argv)
    if not args.check:
        if os.geteuid() == 0:
            print("Do not run the TV browser as root.", file=sys.stderr)
            return 1
        before = {}
        try:
            before = browser_security_state()
            after = drop_browser_privileges()
        except (OSError, RuntimeError, ValueError) as error:
            print(
                "Browser privilege setup failed:",
                error,
                "initial state:",
                before,
                file=sys.stderr,
            )
            return 1
        print(
            "Browser privileges:",
            json.dumps({"before": before, "after": after}),
            flush=True,
        )
        if args.check_privileges:
            return 0
    try:
        Gio, GLib, Gtk, WebKit = load_bindings()
    except (ImportError, ValueError) as error:
        print("WebKitGTK 6.0 / GTK4 is unavailable:", error, file=sys.stderr)
        return 1
    if args.check:
        print("GTK4 and WebKitGTK 6.0 bindings available")
        return 0

    class TVApplication(Gtk.Application):
        def __init__(self):
            super().__init__(
                application_id="ua.lyceumtv.OrangePi",
                flags=Gio.ApplicationFlags.NON_UNIQUE,
            )
            self.failed = False
            self.retry = 0
            self.cursor_refresh = 0
            self.connect("activate", self.activate_tv)

        def activate_tv(self, _application):
            try:
                self.build_tv()
            except Exception:
                traceback.print_exc()
                self.failed = True
                self.quit()

        def build_tv(self):
            configure_gtk_cursor(Gtk)
            settings = make_settings(WebKit)
            profile = Path.home() / ".local/share/lyceumtv-webkit"
            cache = Path.home() / ".cache/lyceumtv-webkit"
            for directory in (profile, cache):
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                directory.chmod(0o700)
            session = WebKit.NetworkSession.new(str(profile), str(cache))
            session.set_persistent_credential_storage_enabled(False)
            session.connect(
                "download-started", lambda _session, download: download.cancel()
            )
            context = WebKit.WebContext.new()
            context.set_cache_model(WebKit.CacheModel.DOCUMENT_VIEWER)
            policies = WebKit.WebsitePolicies(autoplay=WebKit.AutoplayPolicy.ALLOW)
            self.view = WebKit.WebView(
                web_context=context,
                network_session=session,
                website_policies=policies,
                settings=settings,
            )
            self.view.connect("decide-policy", self.decide_policy)
            self.view.connect("permission-request", self.deny_permission)
            self.view.connect("context-menu", lambda *_args: True)
            self.view.connect("create", lambda *_args: None)
            self.view.connect("web-process-terminated", self.process_terminated)
            self.view.connect("load-failed", self.load_failed)
            self.view.connect("load-changed", self.load_changed)
            self.view.set_cursor_from_name("none")
            self.window = Gtk.ApplicationWindow(
                application=self, title="LyceumTV — Orange Pi"
            )
            self.window.set_child(self.view)
            present_kiosk_window(self.window)
            print(
                "GTK cursor: window=none theme="
                + str(Gtk.Settings.get_default().get_property("gtk-cursor-theme-name")),
                flush=True,
            )
            self.view.load_uri(TV_URL)

        def load_changed(self, _view, event):
            if event == WebKit.LoadEvent.FINISHED and not self.cursor_refresh:
                self.cursor_refresh = GLib.timeout_add(150, self.refresh_cursor)

        def refresh_cursor(self):
            self.cursor_refresh = 0
            try:
                refreshed = refresh_seat_cursor()
                print(
                    "Cursor seat refresh: "
                    + (
                        "virtual pointer removed"
                        if refreshed
                        else "protocol unavailable"
                    ),
                    flush=True,
                )
            except (OSError, RuntimeError, KeyError, ValueError, struct.error) as error:
                print("Cursor seat refresh unavailable:", error, flush=True)
            return GLib.SOURCE_REMOVE

        def decide_policy(self, _view, decision, kind):
            if kind in (
                WebKit.PolicyDecisionType.NAVIGATION_ACTION,
                WebKit.PolicyDecisionType.NEW_WINDOW_ACTION,
            ):
                uri = decision.get_navigation_action().get_request().get_uri()
                if (
                    kind == WebKit.PolicyDecisionType.NEW_WINDOW_ACTION
                    or not allowed_navigation(uri)
                ):
                    decision.ignore()
                    return True
            return False

        def deny_permission(self, _view, request):
            request.deny()
            return True

        def load_failed(self, _view, _event, _uri, error):
            if not self.retry:
                print("TV load failed; retrying:", error, flush=True)
                self.retry = GLib.timeout_add_seconds(5, self.reload_tv)
            return True

        def reload_tv(self):
            self.retry = 0
            self.view.load_uri(TV_URL)
            return GLib.SOURCE_REMOVE

        def process_terminated(self, _view, reason):
            print(
                "WebKit process terminated; systemd will restart the kiosk:",
                reason,
                flush=True,
            )
            self.failed = True
            self.quit()

    application = TVApplication()
    status = application.run([sys.argv[0]])
    return 1 if application.failed else status


if __name__ == "__main__":
    raise SystemExit(main())

PYHOST
sudo chown root:root "$new_host"
sudo chmod 644 "$new_host"
sudo mv -f -- "$new_host" /usr/local/lib/lyceumtv/kiosk_browser.py
new_host=""
sudo -u lyceumtv-kiosk /usr/bin/python3 -I /usr/local/lib/lyceumtv/kiosk_browser.py --check-privileges
sudo systemctl daemon-reload
started=$(date +%s)
sudo systemctl restart lyceumtv-kiosk.service
if /usr/bin/python3 -I - <<'PYCHECK'
"""Reject a kiosk restart loop even while systemd briefly reports active."""

import subprocess
import sys
import time


def read_snapshot():
    result = subprocess.check_output(
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
        ],
        text=True,
        timeout=5,
    )
    return dict(line.split("=", 1) for line in result.splitlines() if "=" in line)


def require_running(snapshot):
    if (
        snapshot.get("ActiveState") != "active"
        or snapshot.get("SubState") != "running"
        or not str(snapshot.get("MainPID", "")).isdigit()
        or int(snapshot.get("MainPID", "0")) <= 0
    ):
        raise RuntimeError("Kiosk is not running: " + str(snapshot))


def wait_for_stable(seconds=20, read=read_snapshot, sleep=time.sleep):
    baseline = read()
    require_running(baseline)
    for _ in range(seconds):
        sleep(1)
        current = read()
        require_running(current)
        if any(
            current.get(key) != baseline.get(key) for key in ("MainPID", "NRestarts")
        ):
            raise RuntimeError("Kiosk restarted during verification: " + str(current))

try:
    wait_for_stable()
except (OSError, RuntimeError, subprocess.SubprocessError) as error:
    print(str(error), file=sys.stderr)
    raise SystemExit(1)
PYCHECK
then
  echo "Kiosk process remained stable for 20 seconds; check the TV picture."
  kiosk_uid=$(id -u lyceumtv-kiosk)
  sudo journalctl -b "_UID=$kiosk_uid" --since "@$started" -n 30 --no-pager
else
  sudo journalctl -u lyceumtv-kiosk.service --since "@$started" -n 25 --no-pager
  kiosk_uid=$(id -u lyceumtv-kiosk)
  sudo journalctl -b "_UID=$kiosk_uid" --since "@$started" -n 60 --no-pager
  exit 1
fi
systemctl show --no-pager lyceumtv-kiosk.service -p ActiveState -p SubState -p NRestarts -p NoNewPrivileges -p CapabilityBoundingSet -p AmbientCapabilities
confirmed=false
for attempt in $(seq 1 20); do
  if sudo journalctl -b "_UID=$kiosk_uid" --since "@$started" --no-pager -q -n 1 --grep='Cursor seat refresh: virtual pointer removed' >/dev/null; then
    confirmed=true
    break
  fi
  sleep 1
done
if [ "$confirmed" != true ]; then
  echo "The browser did not confirm pointer refresh. Send the log below."
  sudo journalctl -b "_UID=$kiosk_uid" --since "@$started" -n 60 --no-pager
  exit 1
fi
echo "Cursor seat refresh was confirmed by the running browser; check the TV picture."
sudo journalctl -u lyceumtv-kiosk.service --since "@$started" -n 12 --no-pager
systemctl is-active --quiet lyceumtv-kiosk.service
'@
$temporaryPath = Join-Path $env:TEMP ("lyceumtv-kiosk-fix-" + [guid]::NewGuid().ToString("N") + ".sh")
$remotePath = "/home/$BoardUser/lyceumtv-kiosk-fix-$([guid]::NewGuid().ToString('N')).sh"
$target = "${BoardUser}@${BoardHost}"
try {
    # A file preserves Python/shell quotes across Windows PowerShell 5.1 and SSH.
    [System.IO.File]::WriteAllText($temporaryPath, $remoteCode.Replace("`r", "") + "`n", [System.Text.UTF8Encoding]::new($false))
    & scp -o ConnectTimeout=10 $temporaryPath "${target}:$remotePath"
    if ($LASTEXITCODE -ne 0) { throw "Cannot upload kiosk repair." }
    & ssh -o ConnectTimeout=10 -t $target "bash '$remotePath'"
    if ($LASTEXITCODE -ne 0) { throw "Kiosk repair did not finish. Send the output above." }
}
finally {
    Remove-Item $temporaryPath -ErrorAction SilentlyContinue
}
Write-Host "Kiosk settings applied. Check the TV picture; this does not update the backend version."
