param(
    [string]$BoardHost = "",
    [string]$BoardUser = "admin"
)
$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($BoardHost)) { $BoardHost = Read-Host "Enter Orange Pi IPv4 address" }

$parsedIP = $null
if (-not [System.Net.IPAddress]::TryParse($BoardHost, [ref]$parsedIP) -or $parsedIP.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) { throw "BoardHost must be an IPv4 address." }
if ($BoardUser -notmatch '^[a-z_][a-z0-9_-]{0,31}$') { throw "Invalid Linux username." }
Write-Host "Read-only security checks on your Orange Pi. Enter sudo password if requested."
& ssh -o ConnectTimeout=10 -t "${BoardUser}@${BoardHost}" "sudo /usr/local/sbin/lyceumtv-security-audit '$BoardHost'"
if ($LASTEXITCODE -ne 0) { throw "Security checks reported failures; review the PASS/FAIL output above." }
