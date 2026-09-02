param(
  [int]$BackendPort = 8018,
  [int]$FrontendPort = 5178
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackendDir = Join-Path $ProjectRoot "app\backend"
$FrontendDir = Join-Path $ProjectRoot "app\frontend"
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Requirements = Join-Path $BackendDir "requirements.txt"
$NodeModules = Join-Path $FrontendDir "node_modules"
$LogDir = Join-Path $ProjectRoot "logs"

function Test-PortInUse {
  param([int]$Port)
  $connection = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
  return $null -ne $connection
}

function Find-FreePort {
  param([int]$StartPort)
  $port = $StartPort
  while (Test-PortInUse -Port $port) {
    $port += 1
  }
  return $port
}

function Require-Command {
  param(
    [string]$Name,
    [string]$InstallHint
  )
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    throw "$Name was not found. $InstallHint"
  }
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

Require-Command -Name "node" -InstallHint "Install Node.js, then run this launcher again."
Require-Command -Name "npm" -InstallHint "Install Node.js with npm, then run this launcher again."

if (-not (Test-Path $PythonExe)) {
  Require-Command -Name "python" -InstallHint "Install Python 3, then run this launcher again."
  Write-Host "[DHJR] Creating local Python virtual environment..."
  python -m venv (Join-Path $ProjectRoot ".venv")
}

Write-Host "[DHJR] Installing backend dependencies..."
& $PythonExe -m pip install -r $Requirements | Tee-Object -FilePath (Join-Path $LogDir "backend_install.log")

if (-not (Test-Path $NodeModules)) {
  Write-Host "[DHJR] Installing frontend dependencies..."
  Push-Location $FrontendDir
  npm install | Tee-Object -FilePath (Join-Path $LogDir "frontend_install.log")
  Pop-Location
}

$BackendPort = Find-FreePort -StartPort $BackendPort
$FrontendPort = Find-FreePort -StartPort $FrontendPort
$FrontendUrl = "http://127.0.0.1:$FrontendPort/"
$BackendUrl = "http://127.0.0.1:$BackendPort"

$env:DHJR_WORKSPACE = $ProjectRoot
$env:DHJR_BACKEND_PORT = "$BackendPort"
$env:DHJR_FRONTEND_ORIGIN = $FrontendUrl.TrimEnd("/")
$env:VITE_API_BASE_URL = $BackendUrl

Write-Host "[DHJR] Starting backend on $BackendUrl ..."
$backendArgs = @(
  "-NoExit",
  "-NoProfile",
  "-Command",
  "`$env:DHJR_WORKSPACE='$ProjectRoot'; `$env:DHJR_BACKEND_PORT='$BackendPort'; cd '$ProjectRoot'; & '$PythonExe' -m uvicorn main:app --app-dir app\backend --host 127.0.0.1 --port $BackendPort"
)
Start-Process powershell -ArgumentList $backendArgs -WindowStyle Normal

Start-Sleep -Seconds 2

Write-Host "[DHJR] Starting frontend on $FrontendUrl ..."
$frontendArgs = @(
  "-NoExit",
  "-NoProfile",
  "-Command",
  "`$env:VITE_API_BASE_URL='$BackendUrl'; cd '$FrontendDir'; npm run dev -- --host 127.0.0.1 --port $FrontendPort"
)
Start-Process powershell -ArgumentList $frontendArgs -WindowStyle Normal

Start-Sleep -Seconds 3
Start-Process $FrontendUrl

Write-Host ""
Write-Host "[DHJR] Started."
Write-Host "[DHJR] Frontend: $FrontendUrl"
Write-Host "[DHJR] Backend : $BackendUrl/health"
Write-Host ""
Write-Host "You can close this window. Close the backend/frontend PowerShell windows to stop the app."
