# Launch Chrome for Playwright CDP attach (bypasses Cloudflare bot detection).
# 1. Run this script once before starting the backend
# 2. Set PLAYWRIGHT_CDP_URL=http://127.0.0.1:9222 in backend/.env
# 3. Restart the backend and run your pipeline

$ProfileDir = Join-Path $env:LOCALAPPDATA "DonoChromeProfile"
New-Item -ItemType Directory -Force -Path $ProfileDir | Out-Null

$ChromePaths = @(
    "${env:ProgramFiles}\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)

$Chrome = $ChromePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Chrome) {
    Write-Error "Google Chrome not found. Install Chrome or set path manually."
    exit 1
}

Write-Host "Starting Chrome with remote debugging on port 9222..."
Write-Host "Profile: $ProfileDir"
Write-Host ""
Write-Host "Add to backend/.env:"
Write-Host "  PLAYWRIGHT_CDP_URL=http://127.0.0.1:9222"
Write-Host ""
Write-Host "Keep this Chrome window open while running pipelines."

Start-Process -FilePath $Chrome -ArgumentList @(
    "--remote-debugging-port=9222",
    "--user-data-dir=$ProfileDir",
    "about:blank"
)
