param(
    [string]$BoardHost = "",
    [string]$BoardUser = "admin",
    [switch]$NoReboot
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($BoardHost)) { $BoardHost = Read-Host "Enter Orange Pi IPv4 address" }

$parsedIP = $null
if (-not [System.Net.IPAddress]::TryParse($BoardHost, [ref]$parsedIP) -or $parsedIP.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) { throw "BoardHost must be an IPv4 address." }
if ($BoardUser -notmatch '^[a-z_][a-z0-9_-]{0,31}$') { throw "Invalid Linux username." }
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = "${BoardUser}@${BoardHost}"
$remote = "/home/$BoardUser/LyceumTV-3.7.3-upload-$([guid]::NewGuid().ToString('N'))"

Write-Host "================================================="
Write-Host " LyceumTV 3.7.3 ORANGE PI PC"
Write-Host " Orange Pi: $target"
Write-Host "================================================="

foreach ($cmd in @("ssh", "scp")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        throw "$cmd not found. Install Windows OpenSSH Client."
    }
}

Write-Host "[1/5] Checking SSH and preparing remote folder..."
& ssh -o ConnectTimeout=10 $target "mkdir -p '$remote'"
if ($LASTEXITCODE -ne 0) {
    throw "SSH connection failed. Check Orange Pi IP, username, password/key, and SSH service."
}

$required = @(
    "server",
    "public",
    "data",
    "scripts",
    "README.md",
    "launcher.py"
)
foreach ($item in $required) {
    if (-not (Test-Path (Join-Path $root $item))) {
        throw "Missing required project item: $item"
    }
}

Write-Host "[2/5] Uploading project..."
$uploadItems = @(
    (Join-Path $root "server"),
    (Join-Path $root "public"),
    (Join-Path $root "data"),
    (Join-Path $root "scripts"),
    (Join-Path $root "README.md"),
    (Join-Path $root "launcher.py")
)
$gitignore = Join-Path $root ".gitignore"
if (Test-Path $gitignore) {
    $uploadItems += $gitignore
}

& scp -o ConnectTimeout=10 -r @uploadItems "${target}:$remote/"
if ($LASTEXITCODE -ne 0) {
    throw "Upload failed."
}

Write-Host "[3/5] Running Orange Pi installer..."
Write-Host "Enter the Orange Pi user password if sudo requests it."
& ssh -o ConnectTimeout=10 -t $target "cd '$remote' && chmod +x scripts/*.sh && ./scripts/install.sh '$BoardHost'"
if ($LASTEXITCODE -ne 0) {
    throw "Remote install failed."
}

Write-Host "[4/5] Trusting this Orange Pi HTTPS certificate and checking health..."
$certificatePath = Join-Path $env:TEMP ("lyceumtv-ca-" + [guid]::NewGuid().ToString("N") + ".crt")
try {
    & scp -o ConnectTimeout=10 "${target}:lyceumtv-ca.crt" $certificatePath
    if ($LASTEXITCODE -ne 0) { throw "Cannot retrieve Orange Pi CA through authenticated SSH." }
    $certificate = Import-Certificate -FilePath $certificatePath -CertStoreLocation "Cert:\CurrentUser\Root"
    Write-Host "Orange Pi certificate trusted for the current Windows user: $($certificate.Thumbprint)"
}
finally {
    Remove-Item $certificatePath -ErrorAction SilentlyContinue
}
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$health = $null
for ($attempt = 1; $attempt -le 30; $attempt++) {
    try {
        $health = Invoke-RestMethod `
            -Uri "https://${BoardHost}/api/health" `
            -TimeoutSec 3 `
            -ErrorAction Stop
        break
    }
    catch {
        Write-Host "Waiting for LyceumTV ($attempt/30)..."
        Start-Sleep -Seconds 2
    }
}

if ($null -eq $health) {
    Write-Warning "Server is not responding. Remote diagnostics:"
    & ssh -o ConnectTimeout=10 -t $target "sudo systemctl status lyceumtv --no-pager -l || true; sudo journalctl -u lyceumtv -n 60 --no-pager || true"
    throw "LyceumTV health endpoint is not responding on ${BoardHost}:443"
}

$health | ConvertTo-Json -Depth 6 | Out-Host

if (-not $health.ok -or $health.version -ne "3.7.3") {
    throw "Server reports version $($health.version), expected healthy 3.7.3. Reboot cancelled."
}

try {
    $state = Invoke-RestMethod `
        -Uri "https://${BoardHost}/api/state" `
        -TimeoutSec 8 `
        -ErrorAction Stop

    if ($state.config_public.mobile_public_url) {
        Write-Host "Mobile public URL: $($state.config_public.mobile_public_url)"
    }
}
catch {
    Write-Warning "API state check failed, but health endpoint is OK."
}

# Remove only this successful upload; live files are in /opt/lyceumtv.
& ssh -o ConnectTimeout=10 $target "rm -rf -- '$remote'"
if ($LASTEXITCODE -ne 0) { Write-Warning "Temporary upload folder remains: $remote" }

if (-not $NoReboot) {
    Write-Host "[5/5] Rebooting Orange Pi..."
    & ssh -o ConnectTimeout=10 -t $target "sudo reboot"
    if ($LASTEXITCODE -notin @(0, 255)) { throw "Reboot failed. Run sudo reboot on Orange Pi after checking the error above." }
    Write-Host "Reboot command sent."
}
else {
    Write-Host "[5/5] Reboot skipped."
}

Write-Host ""
Write-Host "Installation complete."
Write-Host "Default role keys have been replaced by unique keys. Retrieve them using SSH and sudo; see README.md."
Write-Host "TV:      https://${BoardHost}/"
Write-Host "Admin:   https://${BoardHost}/admin"
Write-Host "Mobile:  https://${BoardHost}/mobile/"
Write-Host "Ops:     https://${BoardHost}/ops"
Write-Host "Health:  https://${BoardHost}/api/health"
Write-Host "Kiosk:   WebKitGTK 6.0 + Cage"
