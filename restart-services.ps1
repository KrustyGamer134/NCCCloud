# restart-services.ps1
# Stops uvicorn, pulls latest code, runs migrations, then starts backend/agent/frontend in new windows.
# cloudflared is intentionally excluded.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$NCC = "D:\NCC"

# ── 1. Stop any running uvicorn processes ─────────────────────────────────────
# Use WMI to read CommandLine — Get-Process.CommandLine requires PowerShell 7+
Write-Host "Stopping uvicorn processes..." -ForegroundColor Yellow
$uvicornProcs = Get-WmiObject Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*uvicorn*" }

if ($uvicornProcs) {
    $count = @($uvicornProcs).Count
    $uvicornProcs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Write-Host "  Stopped $count uvicorn process(es)." -ForegroundColor Green
} else {
    Write-Host "  No uvicorn processes found." -ForegroundColor DarkGray
}

# ── 2. git pull ───────────────────────────────────────────────────────────────
Write-Host "Pulling latest code..." -ForegroundColor Yellow
Push-Location $NCC
try {
    git pull origin main
    if ($LASTEXITCODE -ne 0) { throw "git pull failed (exit $LASTEXITCODE)" }
    Write-Host "  git pull OK." -ForegroundColor Green
} finally {
    Pop-Location
}

# ── 3. Alembic migrations ─────────────────────────────────────────────────────
Write-Host "Running alembic upgrade head..." -ForegroundColor Yellow
Push-Location "$NCC\ncc-backend"
try {
    & ".venv\Scripts\python.exe" -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "alembic upgrade head failed (exit $LASTEXITCODE)" }
    Write-Host "  Migrations OK." -ForegroundColor Green
} finally {
    Pop-Location
}

# ── 4. Start backend ──────────────────────────────────────────────────────────
Write-Host "Starting backend..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location 'D:\NCC\ncc-backend'; & '.venv\Scripts\python.exe' -m uvicorn main:app --host 0.0.0.0 --port 8000"
) -WindowStyle Normal

# ── 5. Start agent ────────────────────────────────────────────────────────────
Write-Host "Starting agent..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location 'D:\NCC\ncc-agent'; & '.venv\Scripts\python.exe' main.py"
) -WindowStyle Normal

# ── 6. Start frontend ─────────────────────────────────────────────────────────
Write-Host "Starting frontend..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location 'D:\NCC\ncc-frontend'; npm run dev"
) -WindowStyle Normal

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "All services restarted." -ForegroundColor Cyan
