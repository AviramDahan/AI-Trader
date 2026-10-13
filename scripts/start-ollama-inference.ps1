param(
    [Parameter(Mandatory=$true)][string]$IdentityFile,
    [Parameter(Mandatory=$true)][string]$KnownHostsFile,
    [Parameter(Mandatory=$true)][string]$PythonExecutable
)
$ErrorActionPreference = 'Stop'
# No .env, DB credentials, admin SSH key, local workers or trading startup.
$inferenceKey = (Resolve-Path -LiteralPath $IdentityFile).Path
$inferenceHosts = (Resolve-Path -LiteralPath $KnownHostsFile).Path
$inferencePython = (Resolve-Path -LiteralPath $PythonExecutable).Path
$gatewayPath = Join-Path $PSScriptRoot 'ollama_inference_gateway.py'
$gatewayProcess = Start-Process -FilePath $inferencePython -ArgumentList @('"'+$gatewayPath+'"') -WindowStyle Hidden -PassThru
try {
    # Sleep/disconnect tears down the socket; bounded reconnect, no scan/replay.
    while (-not $gatewayProcess.HasExited) {
        & ssh.exe -NT -i $inferenceKey -o "UserKnownHostsFile=$inferenceHosts" `
            -o StrictHostKeyChecking=yes -o BatchMode=yes -o ExitOnForwardFailure=yes `
            -o ServerAliveInterval=15 -o ServerAliveCountMax=2 -o ConnectTimeout=10 `
            -R /opt/ai-trader-ollama/relay.sock:127.0.0.1:11435 ai-inference@2.28.100.77
        if (-not $gatewayProcess.HasExited) { Start-Sleep -Seconds 30 }
    }
}
finally {
    if (-not $gatewayProcess.HasExited) { Stop-Process -Id $gatewayProcess.Id }
}
