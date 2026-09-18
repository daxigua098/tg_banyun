param(
    [switch]$SkipHistory
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$DataDir = Join-Path $ProjectRoot 'data'
$PidFile = Join-Path $DataDir 'runtime.pid'
$StdoutLog = Join-Path $DataDir 'runtime.stdout.log'
$StderrLog = Join-Path $DataDir 'runtime.stderr.log'

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python executable not found: $Python"
}

New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

if (Test-Path -LiteralPath $PidFile) {
    $existingPid = [int](Get-Content -Raw -LiteralPath $PidFile)
    if (Get-Process -Id $existingPid -ErrorAction SilentlyContinue) {
        Write-Output "Already running with PID $existingPid"
        exit 0
    }
    Remove-Item -LiteralPath $PidFile -Force
}

$arguments = @('main.py', 'run')
if ($SkipHistory) {
    $arguments += '--skip-history'
}

$process = Start-Process `
    -FilePath $Python `
    -ArgumentList $arguments `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $StdoutLog `
    -RedirectStandardError $StderrLog `
    -PassThru

Set-Content -LiteralPath $PidFile -Value $process.Id -Encoding ascii
Write-Output "Started PID $($process.Id)"
