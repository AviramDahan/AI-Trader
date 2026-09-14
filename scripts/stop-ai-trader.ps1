[CmdletBinding()]
param([switch]$Quiet)
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $projectRoot '.runtime'
New-Item -ItemType File -Force -Path (Join-Path $runtimeDir 'stop.request') | Out-Null
for ($attempt = 0; $attempt -lt 25; $attempt++) {
    $supervisor = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object {
        $_.CommandLine -like '*supervise_ai_trader.py*' -and $_.CommandLine -like "*$projectRoot*"
    }
    if (-not $supervisor) { break }
    Start-Sleep -Seconds 1
}
if ($supervisor) { throw 'Shutdown is still in progress; rerun stop in a minute. No unrelated process was killed.' }
foreach ($name in @('tunnel', 'backend')) {
    $pidFile = Join-Path $runtimeDir "$name.pid"
    if (-not (Test-Path $pidFile)) { continue }
    $processId = [int](Get-Content -Raw $pidFile)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId"
    $expected = if ($name -eq 'backend') { '*uvicorn main:app*' } else { '*80:127.0.0.1:8000*serveo.net*' }
    if ($process -and $process.CommandLine -like $expected) { Stop-Process -Id $processId -ErrorAction SilentlyContinue }
    Remove-Item -LiteralPath $pidFile -ErrorAction SilentlyContinue
}
if (-not $Quiet) { Write-Output 'AI-Trader stopped. It will start again at next Windows login; disable the AI-Trader-Paper task to remove autostart.' }
