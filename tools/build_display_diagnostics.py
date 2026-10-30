"""Generate a single Windows diagnostic with a file transport for PS 5.1."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
builder = (ROOT / "tools/build_kiosk_repair.py").read_text()
header = builder.split('header = """', 1)[1].split('Write-Host "Repairing', 1)[0]
source = (ROOT / "scripts/display_diagnostics.py").read_text().rstrip()
payload = (
    """Write-Host "Collecting first-boot display diagnostics; leave the TV unchanged."
$remoteCode = @'
set -eu
trap 'rm -f -- "$0"' EXIT
sudo /usr/bin/python3 -I - <<'PYDIAG'
"""
    + source
    + """
PYDIAG
'@
$temporaryPath = Join-Path $env:TEMP ("lyceumtv-diagnostic-" + [guid]::NewGuid().ToString("N") + ".sh")
$remotePath = "/home/$BoardUser/lyceumtv-diagnostic-$([guid]::NewGuid().ToString('N')).sh"
$target = "${BoardUser}@${BoardHost}"
$logPath = Join-Path $PSScriptRoot ("LyceumTV-HDMI-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".txt")
try {
    [System.IO.File]::WriteAllText($temporaryPath, $remoteCode.Replace("`r", "") + "`n", [System.Text.UTF8Encoding]::new($false))
    & scp -o ConnectTimeout=10 $temporaryPath "${target}:$remotePath"
    if ($LASTEXITCODE -ne 0) { throw "Cannot upload diagnostic." }
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & ssh -o ConnectTimeout=10 -o LogLevel=ERROR -t $target "bash '$remotePath'" 2>&1 | Tee-Object -FilePath $logPath
        $diagnosticExit = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previousPreference }
    if ($diagnosticExit -ne 0) { throw "Diagnostic did not finish. Send the saved log: $logPath" }
}
finally { Remove-Item $temporaryPath -ErrorAction SilentlyContinue }
Write-Host "Send this file: $logPath"
"""
)
(ROOT / "CHECK_ORANGEPI.ps1").write_text(header + payload, encoding="utf-8-sig")
print("Generated read-only CHECK_ORANGEPI.ps1")
