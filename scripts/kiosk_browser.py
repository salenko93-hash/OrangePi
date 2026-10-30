"""Small GTK4/WebKitGTK TV host for Orange Pi PC; no desktop or Snap browser."""

import argparse
import os
from pathlib import Path
import sys
import traceback
from urllib.parse import urlsplit

TV_URL = "http://127.0.0.1:8080/?screen=main-hall&lite=1"


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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Check GI packages; no display required"
    )
    args = parser.parse_args(argv)
    try:
        Gio, GLib, Gtk, WebKit = load_bindings()
    except (ImportError, ValueError) as error:
        print("WebKitGTK 6.0 / GTK4 is unavailable:", error, file=sys.stderr)
        return 1
    if args.check:
        print("GTK4 and WebKitGTK 6.0 bindings available")
        return 0
    if os.geteuid() == 0:
        print("Do not run the TV browser as root.", file=sys.stderr)
        return 1

    class TVApplication(Gtk.Application):
        def __init__(self):
            super().__init__(
                application_id="ua.lyceumtv.OrangePi",
                flags=Gio.ApplicationFlags.NON_UNIQUE,
            )
            self.failed = False
            self.retry = 0
            self.connect("activate", self.activate_tv)

        def activate_tv(self, _application):
            try:
                self.build_tv()
            except Exception:
                traceback.print_exc()
                self.failed = True
                self.quit()

        def build_tv(self):
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
            self.view.set_cursor_from_name("none")
            self.window = Gtk.ApplicationWindow(
                application=self, title="LyceumTV — Orange Pi"
            )
            self.window.set_decorated(False)
            self.window.set_default_size(1280, 720)
            self.window.set_child(self.view)
            self.window.fullscreen()
            self.window.present()
            self.view.load_uri(TV_URL)

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
