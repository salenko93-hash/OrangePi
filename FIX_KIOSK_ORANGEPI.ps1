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
Write-Host "Repairing kiosk privilege/cache settings on ${BoardUser}@${BoardHost}..."
$remoteCode = @'
set -eu
sudo -v
trap 'rm -f -- "$0"; sudo systemctl start lyceumtv-watchdog.timer' EXIT
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
