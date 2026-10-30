param(
    [string]$BoardHost = "",
    [string]$BoardUser = "admin"
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($BoardHost)) { $BoardHost = Read-Host "Enter Orange Pi IPv4 address" }

$target = "${BoardUser}@${BoardHost}"

$parsedIP = $null
if (-not [System.Net.IPAddress]::TryParse($BoardHost, [ref]$parsedIP) -or $parsedIP.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) { throw "BoardHost must be an IPv4 address." }
if ($BoardUser -notmatch '^[a-z_][a-z0-9_-]{0,31}$') { throw "Invalid Linux username." }
if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    throw "ssh not found. Install Windows OpenSSH Client."
}

Write-Host "Checking Orange Pi: $target"
Write-Host ""

& ssh -o ConnectTimeout=10 -t $target @'
set +e
echo "=== API ==="
curl -fsS http://127.0.0.1:8080/api/health
echo
echo
echo "=== SERVICES ==="
for s in lyceumtv.service lyceumtv-kiosk.service lyceumtv-watchdog.timer nginx.service; do
  printf "%-28s " "$s"
  systemctl is-active "$s"
done
echo
echo "=== KIOSK RESTARTS / PRIVILEGES ==="
systemctl show --no-pager lyceumtv-kiosk.service -p MainPID -p NRestarts -p ExecMainStatus -p NoNewPrivileges -p CapabilityBoundingSet -p AmbientCapabilities
kiosk_pid=$(systemctl show --no-pager lyceumtv-kiosk.service -p MainPID --value)
for attempt in 1 2 3 4 5 6 7 8; do
  if [ "$kiosk_pid" -gt 0 ] 2>/dev/null && [ -r "/proc/$kiosk_pid/status" ]; then break; fi
  sleep 1
  kiosk_pid=$(systemctl show --no-pager lyceumtv-kiosk.service -p MainPID --value)
done
if [ "$kiosk_pid" -gt 0 ] 2>/dev/null && [ -r "/proc/$kiosk_pid/status" ]; then
  sed -n '/^Cap/p; /^NoNewPrivs:/p' "/proc/$kiosk_pid/status"
else
  echo "No live kiosk PID captured: service is stopped or between restarts."
fi
for browser_pid in $(pgrep -u lyceumtv-kiosk -f kiosk_browser.py); do
  echo "Browser PID=$browser_pid"
  sudo sed -n '/^Cap/p; /^NoNewPrivs:/p' "/proc/$browser_pid/status" || true
done
if command -v getcap >/dev/null 2>&1; then
  getcap /usr/bin/bwrap /usr/bin/cage /usr/bin/python3 2>/dev/null || true
fi
echo
echo "=== BOOT TARGET ==="
systemctl get-default
echo
echo "=== DISPLAY MODES ==="
for f in /sys/class/drm/*HDMI*/modes; do
  [ -f "$f" ] || continue
  echo "-- $f"
  head -n 8 "$f"
done
echo
echo "=== KIOSK LOG TAIL ==="
sudo journalctl -u lyceumtv-kiosk.service -n 30 --no-pager || true
kiosk_uid=$(id -u lyceumtv-kiosk 2>/dev/null)
if [ -n "$kiosk_uid" ]; then
  sudo journalctl -b "_UID=$kiosk_uid" -n 60 --no-pager || true
fi
echo "=== NETWORK / MEMORY / AUDIO ==="
ip -br addr
free -h
swapon --show
aplay -l 2>/dev/null || true
'@

if ($LASTEXITCODE -ne 0) {
    Write-Warning "One or more remote checks returned a non-zero exit code."
}

Write-Host ""
Write-Host "TV:       https://${BoardHost}/"
Write-Host "Admin:    https://${BoardHost}/admin"
Write-Host "Ops:      https://${BoardHost}/ops"
Write-Host "UI debug: https://${BoardHost}/?debug=1"
Write-Host "Mobile:   https://${BoardHost}/mobile/"
