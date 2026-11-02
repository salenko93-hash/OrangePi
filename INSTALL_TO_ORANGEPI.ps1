param(
    [string]$BoardHost = "",
    [string]$BoardUser = "admin",
    [switch]$NoReboot,
    [switch]$CheckOnly,
    [string]$Tag = "",
    [string]$ApproveVersion = "",
    [switch]$AllowPrerelease
)
$ErrorActionPreference = "Stop"
# Verified releases contain server, public, data and scripts; never upload live data.
if ([string]::IsNullOrWhiteSpace($BoardHost)) { $BoardHost = Read-Host "Enter Orange Pi IPv4 address" }
$arguments = @{ BoardHost=$BoardHost; BoardUser=$BoardUser; Tag=$Tag; ApproveVersion=$ApproveVersion }
if ($CheckOnly) { $arguments.CheckOnly=$true }
if ($AllowPrerelease) { $arguments.AllowPrerelease=$true }
# The new installer never requests a reboot. NoReboot remains accepted for callers.
& (Join-Path $PSScriptRoot "INSTALL_RELEASE_ORANGEPI.ps1") @arguments
