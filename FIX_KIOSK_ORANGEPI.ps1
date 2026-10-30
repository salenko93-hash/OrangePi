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
Write-Host "Repairing kiosk 3.7.2 (runtime capability drop) on ${BoardUser}@${BoardHost}..."
$remoteCode = @'
set -eu
sudo -v
new_host=""
trap 'if [ -n "$new_host" ]; then sudo rm -f -- "$new_host"; fi; rm -f -- "$0"; sudo systemctl start lyceumtv-watchdog.timer' EXIT
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
if loginctl show-user --no-pager lyceumtv-kiosk >/dev/null 2>&1; then
  sudo loginctl terminate-user lyceumtv-kiosk
fi
sudo test -d /usr/local/lib/lyceumtv
if [ ! -e /usr/local/lib/lyceumtv/kiosk_browser.py.before-3.7.2 ]; then
  sudo cp -p /usr/local/lib/lyceumtv/kiosk_browser.py /usr/local/lib/lyceumtv/kiosk_browser.py.before-3.7.2
fi
new_host=$(sudo mktemp /usr/local/lib/lyceumtv/.kiosk-browser-XXXXXX)
sudo tee "$new_host" >/dev/null <<'PYHOST'
"""Small GTK4/WebKitGTK TV host for Orange Pi PC; no desktop or Snap browser."""

import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
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
else
  sudo journalctl -u lyceumtv-kiosk.service --since "@$started" -n 25 --no-pager
  kiosk_uid=$(id -u lyceumtv-kiosk)
  sudo journalctl -b "_UID=$kiosk_uid" --since "@$started" -n 60 --no-pager
  exit 1
fi
systemctl show --no-pager lyceumtv-kiosk.service -p ActiveState -p SubState -p NRestarts -p NoNewPrivileges -p CapabilityBoundingSet -p AmbientCapabilities
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
