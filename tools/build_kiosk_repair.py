"""Regenerate the standalone PowerShell repair from the canonical profile helper."""

from pathlib import Path

root = Path(__file__).resolve().parents[1]
profile = (
    (root / "scripts/kiosk_profile.py")
    .read_text()
    .split("\ndef main():", 1)[0]
    .rstrip()
)
check = (
    (root / "scripts/kiosk_stability.py")
    .read_text()
    .split("\ndef main():", 1)[0]
    .rstrip()
)
browser = (root / "scripts/kiosk_browser.py").read_text().rstrip()
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
Write-Host "Repairing kiosk 3.7.3 (runtime capability drop) on ${BoardUser}@${BoardHost}..."
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
"""
footer = """
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
if [ ! -e /usr/local/lib/lyceumtv/kiosk_browser.py.before-3.7.3 ]; then
  sudo cp -p /usr/local/lib/lyceumtv/kiosk_browser.py /usr/local/lib/lyceumtv/kiosk_browser.py.before-3.7.3
fi
new_host=$(sudo mktemp /usr/local/lib/lyceumtv/.kiosk-browser-XXXXXX)
sudo tee "$new_host" >/dev/null <<'PYHOST'
"""
install_browser = """
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
"""
verification = """
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
"""
(root / "FIX_KIOSK_ORANGEPI.ps1").write_text(
    header
    + profile
    + "\n"
    + footer
    + browser
    + "\n"
    + install_browser
    + check
    + "\n"
    + verification,
    encoding="utf-8-sig",
)
print("Generated standalone repair from canonical kiosk_profile.py")
