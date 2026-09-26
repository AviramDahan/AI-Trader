[CmdletBinding()]
param([switch]$Wait, [switch]$Watchdog)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $projectRoot '.runtime'
if (Test-Path (Join-Path $runtimeDir 'cloud-writer.lock')) {
    throw 'Cloud handover lock: do not restart stale local state. Stop cloud writers and restore current cloud state before any rollback.'
}
if ($Watchdog -and (Test-Path (Join-Path $runtimeDir 'stop.request'))) { exit 0 }
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $pythonExe)) { throw 'Install service/requirements.txt into .venv first.' }
if (-not (Test-Path (Join-Path $projectRoot 'PRIVATE_SETUP_CREDENTIALS.txt'))) {
    & $pythonExe (Join-Path $PSScriptRoot 'bootstrap_private_setup.py')
    if ($LASTEXITCODE -ne 0) { throw 'Private setup failed.' }
}
& $pythonExe (Join-Path $PSScriptRoot 'configure_stock_scanner.py')
if ($LASTEXITCODE -ne 0) { throw 'Stock scanner configuration failed.' }
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
$existing = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object {
    $_.CommandLine -like '*supervise_ai_trader.py*' -and $_.CommandLine -like "*$projectRoot*"
}
if ($existing) { Write-Output 'AI-Trader supervisor is already running.'; exit 0 }
Remove-Item -LiteralPath (Join-Path $runtimeDir 'stop.request') -ErrorAction SilentlyContinue
$supervisor = Start-Process -FilePath $pythonExe `
    -ArgumentList @('-u', ('"' + (Join-Path $PSScriptRoot 'supervise_ai_trader.py') + '"')) `
    -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $runtimeDir 'supervisor.log') `
    -RedirectStandardError (Join-Path $runtimeDir 'supervisor.stderr.log')
Start-Sleep -Seconds 3
if ($supervisor.HasExited) { throw 'Supervisor could not start. Check .runtime/supervisor.stderr.log.' }
Write-Output 'AI-Trader supervisor started. Backend/tunnel recovery and Pages updates are automatic.'
Write-Output 'Open https://aviramdahan.github.io/AI-Trader/market (allow a few minutes for deployment).'
if ($Wait) {
    $supervisor.WaitForExit()
    if ($supervisor.ExitCode -ne 0) { throw 'Supervisor exited unexpectedly; Windows Task Scheduler will retry.' }
}
