# Reset Dono CDP Chrome profile — use when Cloudflare shows "Sorry, you have been blocked".
# Run AFTER connecting VPN and BEFORE starting the backend.
#
# Steps:
#   1. Connect VPN (try several US cities if one fails)
#   2. Run this script
#   3. Start backend + pipeline
#   4. In the new Chrome window, manually open the county assessor URL and pass any check
#   5. Then run the assessor workflow (automation reuses your working tab)

$ProfileDir = Join-Path $env:LOCALAPPDATA "DonoChromeProfile"

Write-Host "Stopping Chrome processes..."
Get-Process chrome -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

if (Test-Path $ProfileDir) {
    $Backup = "$ProfileDir.blocked.$(Get-Date -Format 'yyyyMMddHHmmss')"
    Write-Host "Rotating profile: $ProfileDir -> $Backup"
    Rename-Item -Path $ProfileDir -NewName (Split-Path $Backup -Leaf) -ErrorAction SilentlyContinue
    if (Test-Path $ProfileDir) {
        Remove-Item -Recurse -Force $ProfileDir
    }
}

New-Item -ItemType Directory -Force -Path $ProfileDir | Out-Null
Write-Host "Fresh profile created at $ProfileDir"
Write-Host ""
Write-Host "Next: start the backend, run the pipeline, and open the county URL manually in the Chrome window."
