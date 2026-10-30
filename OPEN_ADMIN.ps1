param([string]$BoardHost = "")

if ([string]::IsNullOrWhiteSpace($BoardHost)) { $BoardHost = Read-Host "Enter Orange Pi IPv4 address" }
$parsedIP = $null
if (-not [System.Net.IPAddress]::TryParse($BoardHost, [ref]$parsedIP) -or $parsedIP.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) { throw "BoardHost must be an IPv4 address." }
Start-Process "https://${BoardHost}/admin"
