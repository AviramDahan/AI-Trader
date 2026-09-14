[CmdletBinding()]
param(
    [switch]$SkipPagesDeploy
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $projectRoot '.runtime'
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
$bootstrapScript = Join-Path $PSScriptRoot 'bootstrap_private_setup.py'

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

if (-not (Test-Path $pythonExe)) {
    throw 'Python environment is missing. Run: python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r service\requirements.txt'
}
if (-not (Test-Path (Join-Path $projectRoot 'PRIVATE_SETUP_CREDENTIALS.txt'))) {
    & $pythonExe $bootstrapScript
}

& (Join-Path $PSScriptRoot 'stop-ai-trader.ps1') -Quiet

$backendOut = Join-Path $runtimeDir 'backend.stdout.log'
$backendErr = Join-Path $runtimeDir 'backend.stderr.log'
$tunnelOut = Join-Path $runtimeDir 'tunnel.stdout.log'
$tunnelErr = Join-Path $runtimeDir 'tunnel.stderr.log'

$backend = Start-Process -FilePath $pythonExe `
    -ArgumentList @('-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8000') `
    -WorkingDirectory (Join-Path $projectRoot 'service\server') `
    -RedirectStandardOutput $backendOut -RedirectStandardError $backendErr `
    -WindowStyle Hidden -PassThru
$backend.Id | Set-Content -NoNewline (Join-Path $runtimeDir 'backend.pid')

$healthy = $false
for ($attempt = 0; $attempt -lt 45; $attempt++) {
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 2
        if ($health.status -eq 'ok') { $healthy = $true; break }
    } catch {}
    Start-Sleep -Seconds 1
}
if (-not $healthy) {
    throw "Backend did not become healthy. See $backendErr"
}

$sshExe = (Get-Command ssh.exe -ErrorAction Stop).Source
$tunnel = Start-Process -FilePath $sshExe `
    -ArgumentList @(
        '-T',
        '-o', 'StrictHostKeyChecking=accept-new',
        '-o', 'ServerAliveInterval=30',
        '-o', 'ServerAliveCountMax=3',
        '-o', 'ExitOnForwardFailure=yes',
        '-R', '80:127.0.0.1:8000',
        'serveo.net'
    ) `
    -WorkingDirectory $projectRoot `
    -RedirectStandardOutput $tunnelOut -RedirectStandardError $tunnelErr `
    -WindowStyle Hidden -PassThru
$tunnel.Id | Set-Content -NoNewline (Join-Path $runtimeDir 'tunnel.pid')

$backendUrl = $null
for ($attempt = 0; $attempt -lt 45; $attempt++) {
    $combinedLog = ''
    if (Test-Path $tunnelOut) { $combinedLog += Get-Content -Raw $tunnelOut }
    if (Test-Path $tunnelErr) { $combinedLog += Get-Content -Raw $tunnelErr }
    $match = [regex]::Match($combinedLog, 'https://[a-z0-9-]+\.serveousercontent\.com')
    if ($match.Success) { $backendUrl = $match.Value; break }
    Start-Sleep -Seconds 1
}
if (-not $backendUrl) {
    throw "The Serveo HTTPS tunnel did not produce a public URL. See $tunnelErr"
}

$publicHealthy = $false
$backendHost = ([uri]$backendUrl).Host
for ($attempt = 0; $attempt -lt 45; $attempt++) {
    try {
        $publicHealth = Invoke-RestMethod -Uri "$backendUrl/health" -TimeoutSec 5
        if ($publicHealth.status -eq 'ok') { $publicHealthy = $true; break }
    } catch {}
    Start-Sleep -Seconds 1
}
if (-not $publicHealthy) {
    throw "The public backend health check failed. See $tunnelErr"
}

$backendUrl | Set-Content -NoNewline (Join-Path $runtimeDir 'backend-url.txt')

if (-not $SkipPagesDeploy) {
    gh variable set BACKEND_URL --repo AviramDahan/AI-Trader --body $backendUrl
    gh workflow run deploy-pages.yml --repo AviramDahan/AI-Trader
}

Write-Output "AI-Trader is running. Backend: $backendUrl"
if (-not $SkipPagesDeploy) {
    Write-Output 'GitHub Pages deployment was triggered with the new backend URL.'
}
