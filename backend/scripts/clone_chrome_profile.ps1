# Clone your WORKING regular Chrome profile into DonoChromeProfile.
# Use this when regular Chrome opens the county site but automation Chrome is blocked.
#
# REQUIREMENTS:
#   1. Close ALL Chrome windows first (check Task Manager)
#   2. Regular Chrome must already open schneidercorp.com successfully at least once
#
# Usage:
#   .\clone_chrome_profile.ps1
#   Restart backend and run pipeline

$Source = Join-Path $env:LOCALAPPDATA "Google\Chrome\User Data"
$Dest = Join-Path $env:LOCALAPPDATA "DonoChromeProfile"

if (-not (Test-Path $Source)) {
    Write-Error "Chrome profile not found at $Source"
    exit 1
}

$ChromeRunning = Get-Process chrome -ErrorAction SilentlyContinue
if ($ChromeRunning) {
    Write-Error "Close ALL Chrome windows first, then run this script again."
    exit 1
}

Write-Host "Stopping stray Chrome..."
Get-Process chrome -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

if (Test-Path $Dest) {
    $Backup = "$Dest.cloned.$(Get-Date -Format 'yyyyMMddHHmmss')"
    Write-Host "Backing up old DonoChromeProfile -> $Backup"
    Rename-Item $Dest $Backup -ErrorAction SilentlyContinue
}

Write-Host "Cloning Chrome profile (this may take a minute)..."
robocopy $Source $Dest /E /XD "Cache" "Code Cache" "GPUCache" "Service Worker" "GrShaderCache" /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null

if (-not (Test-Path $Dest)) {
    Write-Error "Clone failed."
    exit 1
}

Write-Host ""
Write-Host "Done. DonoChromeProfile now mirrors your regular Chrome session."
Write-Host "Restart the backend and run the assessor pipeline."
