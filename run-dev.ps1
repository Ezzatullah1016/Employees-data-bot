# Stop anything on the app ports, then start Django on 2000 (matches README).
$ErrorActionPreference = "SilentlyContinue"
foreach ($port in 2000, 8000) {
    Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}
Start-Sleep -Milliseconds 400
Set-Location $PSScriptRoot
if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Error "Missing .venv. Run: py -m venv .venv"
    exit 1
}
Write-Host "Starting http://127.0.0.1:2000/ (Ctrl+C to stop)" -ForegroundColor Green
& ".\.venv\Scripts\python.exe" manage.py runserver 127.0.0.1:2000
