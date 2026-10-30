"""Build a standalone Windows helper from the canonical cursor installer."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
repair_builder = (ROOT / "tools/build_kiosk_repair.py").read_text()
# Reuse the proven PowerShell 5.1 SCP transport; no remote quote interpolation.
transport = repair_builder.split("$temporaryPath =", 1)[1].split('"""', 1)[0]
transport = "$temporaryPath =" + transport
transport = transport.replace("kiosk-fix", "cursor-fix").replace(
    "kiosk repair", "cursor fix"
)
transport = transport.replace(
    "Kiosk repair did not finish", "Cursor fix did not finish"
)
transport = transport.replace(
    "Kiosk settings applied. Check the TV picture; this does not update the backend version.",
    "Cursor hiding configured. Check the TV picture.",
)
header = repair_builder.split('header = """', 1)[1].split('Write-Host "Repairing', 1)[0]
source = (ROOT / "scripts/hide_cursor.py").read_text().rstrip()
check = (
    (ROOT / "scripts/kiosk_stability.py")
    .read_text()
    .split("\ndef main():", 1)[0]
    .rstrip()
)
payload = (
    """Write-Host "Hiding the TV cursor on ${BoardUser}@${BoardHost}..."
$remoteCode = @'
set -eu
trap 'rm -f -- "$0"' EXIT
sudo -v
sudo /usr/bin/python3 -I - <<'PYCURSOR'
"""
    + source
    + """
PYCURSOR
sudo systemctl daemon-reload
started=$(date +%s)
sudo systemctl restart lyceumtv-kiosk.service
if /usr/bin/python3 -I - <<'PYCHECK'
"""
    + check
    + """
try:
    wait_for_stable()
except (OSError, RuntimeError, subprocess.SubprocessError) as error:
    print(str(error), file=sys.stderr)
    raise SystemExit(1)
PYCHECK
then
  echo "Kiosk process remained stable for 20 seconds."
else
  sudo journalctl -u lyceumtv-kiosk.service --since "@$started" -n 30 --no-pager
  exit 1
fi
'@
"""
)
(ROOT / "HIDE_CURSOR_ORANGEPI.ps1").write_text(
    header + payload + transport, encoding="utf-8-sig"
)
print("Generated HIDE_CURSOR_ORANGEPI.ps1")
