param(
    [string]$TaskName = 'TG-Mirror-Bot'
)

$ErrorActionPreference = 'Stop'
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Output "Scheduled task removed: $TaskName"
