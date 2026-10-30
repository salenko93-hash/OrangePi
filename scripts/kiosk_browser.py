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
