param(
    [Parameter(Mandatory=$true)][string]$BoardHost,
    [string]$BoardUser = "admin",
    [string]$Tag = "",
    [string]$ApproveVersion = "",
    [switch]$AllowPrerelease,
    [switch]$CheckOnly
)
$ErrorActionPreference = "Stop"
$address = $null
if (-not [Net.IPAddress]::TryParse($BoardHost, [ref]$address) -or $address.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) { throw "BoardHost must be an IPv4 address." }
if ($BoardUser -notmatch '^[a-z_][a-z0-9_-]{0,31}$') { throw "Invalid Linux username." }
if ($Tag -and $Tag -notmatch '^v?\d+\.\d+\.\d+(-rc\.[1-9]\d*)?$') { throw "Invalid release tag." }
if ($ApproveVersion -and $ApproveVersion -notmatch '^\d+\.\d+\.\d+$') { throw "Invalid approved version." }
foreach ($tool in @("python", "ssh", "scp")) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool is required." }
}
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = "${BoardUser}@${BoardHost}"
$temporary = Join-Path ([IO.Path]::GetTempPath()) ("orangepi-download-" + [guid]::NewGuid().ToString("N"))
try {
    $arguments = @("-B", (Join-Path $root "scripts/github_update.py"), "download", "--output", $temporary)
    if ($Tag) { $arguments += @("--tag", $Tag) }
    if ($AllowPrerelease) { $arguments += "--allow-prerelease" }
    $raw = & python @arguments
    if ($LASTEXITCODE -ne 0) { throw "Official release verification failed: $raw" }
    $release = $raw | ConvertFrom-Json
    if (-not $release.ok -or $release.source -ne "https://github.com/salenko93-hash/OrangePi") { throw "Untrusted release source." }
    $folder = Join-Path $temporary ("LyceumTV-" + $release.version + "-ORANGEPI-PC")
    $zip = Join-Path $temporary $release.name
    if ((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $release.sha256) { throw "Local ZIP changed after download." }
    # This script only reads board metadata and prints JSON. No remote staging yet.
    $code = [Convert]::ToBase64String([IO.File]::ReadAllBytes((Join-Path $folder "scripts/deployment_preflight.py")))
    $python = "import base64;exec(compile(base64.b64decode('$code'),'<verified-preflight>','exec'))"
    & ssh -o ConnectTimeout=10 -t $target "sudo python3 -c `"$python`" --check-only --package-bytes $((Get-Item -LiteralPath $zip).Length)"
    if ($LASTEXITCODE -ne 0) { throw "SSH/model/OS/storage/dependency preflight failed. No installation performed." }
    if ($CheckOnly -or -not $ApproveVersion) {
        Write-Host "PASS: check only; no installation, service changes, or remote upload."
        Write-Host "Selected tag $($release.tag), runtime $($release.version), SHA-256 $($release.sha256)"
        return
    }
    if ($ApproveVersion -ne $release.version) { throw "ApproveVersion must exactly match $($release.version)." }
    if (-not $Tag) { throw "Installation requires an explicit immutable selection via -Tag." }
    $upload = "/tmp/orangepi-upload-$([guid]::NewGuid().ToString('N')).zip"
    & scp -o ConnectTimeout=10 $zip "${target}:$upload"
    if ($LASTEXITCODE -ne 0) { throw "SSH upload failed; nothing installed." }
    $code = [Convert]::ToBase64String([IO.File]::ReadAllBytes((Join-Path $folder "scripts/remote_release.py")))
    $python = "import base64;exec(compile(base64.b64decode('$code'),'<verified-installer>','exec'))"
    $options = "'$upload' --sha256 '$($release.sha256)' --version '$ApproveVersion' --tag '$Tag' --address '$BoardHost' --approve '$ApproveVersion'"
    if ($AllowPrerelease) { $options += " --allow-prerelease" }
    & ssh -o ConnectTimeout=10 -t $target "python3 -c `"$python`" $options"
    if ($LASTEXITCODE -ne 0) { throw "Installation/update failed. Inspect the reported phase, backup and transaction before retrying." }
    Write-Host "PASS: approved release completed; no reboot requested."
}
finally {
    # Delete only this task's local download directory after validating its path.
    $resolved = [IO.Path]::GetFullPath($temporary)
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if ($resolved.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -and (Split-Path -Leaf $resolved) -match '^orangepi-download-[a-f0-9]{32}$') {
        if (Test-Path -LiteralPath $resolved) { Remove-Item -LiteralPath $resolved -Recurse -Force }
    }
}
