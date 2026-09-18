$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $ProjectRoot 'data\runtime.pid'

if (-not (Test-Path -LiteralPath $PidFile)) {
    Write-Output 'Runtime PID file not found.'
    exit 0
}

$processId = [int](Get-Content -Raw -LiteralPath $PidFile)
$process = Get-Process -Id $processId -ErrorAction SilentlyContinue
if ($process) {
    Stop-Process -Id $processId -Force
    Write-Output "Stopped PID $processId"
} else {
    Write-Output "Process $processId is not running."
}

Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
