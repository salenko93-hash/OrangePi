"""Optional real GTK/Cage window probe; requires Gtk 4.0 GI and a compositor.

Run under Cage with WAYLAND_DEBUG=1; --legacy-fullscreen illustrates the old
early request. This tests the actual window setup, without WebKit subprocesses.
"""

import importlib.util
from pathlib import Path
import sys
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "kiosk_window_host", ROOT / "scripts/kiosk_browser.py"
)
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


def run():
    app = Gtk.Application(
        application_id="ua.lyceumtv.WindowProbe", flags=Gio.ApplicationFlags.NON_UNIQUE
    )
    observed = []

    def activate(application):
        host.configure_gtk_cursor(Gtk)
        window = Gtk.ApplicationWindow(
            application=application, title="LyceumTV window probe"
        )
        if "--legacy-fullscreen" in sys.argv:
            window.fullscreen()
        host.present_kiosk_window(window)

        def refresh_cursor():
            try:
                refreshed = host.refresh_seat_cursor()
            except Exception as error:
                print("PROBE_CURSOR_REFRESH_ERROR=" + str(error), flush=True)
                refreshed = False
            observed.append(refreshed)
            print("PROBE_CURSOR_REFRESH=" + str(refreshed), flush=True)
            return False

        GLib.timeout_add(300, refresh_cursor)

        def finish():
            observed.append(window.get_mapped())
            print("PROBE_MAPPED=" + str(window.get_mapped()), flush=True)
            print("PROBE_CURSOR=" + str(window.get_cursor().get_name()), flush=True)
            print(
                "PROBE_CURSOR_THEME="
                + str(Gtk.Settings.get_default().get_property("gtk-cursor-theme-name")),
                flush=True,
            )
            print(
                "PROBE_SIZE=" + str((window.get_width(), window.get_height())),
                flush=True,
            )
            application.quit()
            return False

        GLib.timeout_add_seconds(3, finish)

    app.connect("activate", activate)
    status = app.run([sys.argv[0]])
    return status if status else 0 if observed == [True, True] else 1


if __name__ == "__main__":
    raise SystemExit(run())
