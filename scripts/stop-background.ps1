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
    & taskkill.exe /PID $processId /T /F | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to stop PID $processId. Try running this script as administrator."
    }
    Write-Output "Stopped PID $processId and child processes"
} else {
    Write-Output "Process $processId is not running."
}

Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue


