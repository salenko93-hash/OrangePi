"""Regenerate the standalone PowerShell repair from the canonical profile helper."""

from pathlib import Path

root = Path(__file__).resolve().parents[1]
profile = (
    (root / "scripts/kiosk_profile.py")
    .read_text()
    .split("\ndef main():", 1)[0]
    .rstrip()
)
header = """param(
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
"""
footer = """
import pwd
account = pwd.getpwnam("lyceumtv-kiosk")
if account.pw_uid == 0 or account.pw_dir != "/var/lib/lyceumtv-kiosk":
    raise SystemExit("Refusing unexpected kiosk account/home directory")
prepare_profile(account.pw_dir, account.pw_uid, account.pw_gid)
PYPROFILE
sudo systemctl daemon-reload
sudo systemctl restart lyceumtv-kiosk.service
sleep 8
systemctl show --no-pager lyceumtv-kiosk.service -p ActiveState -p SubState -p NRestarts -p NoNewPrivileges -p CapabilityBoundingSet -p AmbientCapabilities
sudo journalctl -u lyceumtv-kiosk.service -n 12 --no-pager
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
"""
(root / "FIX_KIOSK_ORANGEPI.ps1").write_text(header + profile + "\n" + footer)
print("Generated standalone repair from canonical kiosk_profile.py")
