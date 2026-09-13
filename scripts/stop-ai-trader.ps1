[CmdletBinding()]
param(
    [switch]$Quiet
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $projectRoot '.runtime'

foreach ($name in @('tunnel', 'backend')) {
    $pidFile = Join-Path $runtimeDir "$name.pid"
    if (-not (Test-Path $pidFile)) { continue }
    $processId = [int](Get-Content -Raw $pidFile)
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($process) {
        Stop-Process -Id $processId -ErrorAction SilentlyContinue
        [void]$process.WaitForExit(10000)
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}

if (-not $Quiet) {
    Write-Output 'AI-Trader backend and tunnel are stopped.'
}
