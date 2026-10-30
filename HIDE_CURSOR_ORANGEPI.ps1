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
Write-Host "Applying cursor fix v3 (first startup, software cursor) on ${BoardUser}@${BoardHost}..."
$remoteCode = @'
set -eu
trap 'rm -f -- "$0"' EXIT
sudo -v
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
sudo -u lyceumtv-kiosk test -r /usr/local/share/lyceumtv-cursors/default/cursors/left_ptr
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
  echo "Kiosk process remained stable for 20 seconds."
  sudo journalctl -u lyceumtv-kiosk.service --since "@$started" -n 12 --no-pager
else
  sudo journalctl -u lyceumtv-kiosk.service --since "@$started" -n 30 --no-pager
  exit 1
fi
'@
$temporaryPath = Join-Path $env:TEMP ("lyceumtv-cursor-fix-" + [guid]::NewGuid().ToString("N") + ".sh")
$remotePath = "/home/$BoardUser/lyceumtv-cursor-fix-$([guid]::NewGuid().ToString('N')).sh"
$target = "${BoardUser}@${BoardHost}"
try {
    # A file preserves Python/shell quotes across Windows PowerShell 5.1 and SSH.
    [System.IO.File]::WriteAllText($temporaryPath, $remoteCode.Replace("`r", "") + "`n", [System.Text.UTF8Encoding]::new($false))
    & scp -o ConnectTimeout=10 $temporaryPath "${target}:$remotePath"
    if ($LASTEXITCODE -ne 0) { throw "Cannot upload cursor fix." }
    & ssh -o ConnectTimeout=10 -t $target "bash '$remotePath'"
    if ($LASTEXITCODE -ne 0) { throw "Cursor fix did not finish. Send the output above." }
}
finally {
    Remove-Item $temporaryPath -ErrorAction SilentlyContinue
}
Write-Host "Cursor hiding configured. Check the TV picture."
