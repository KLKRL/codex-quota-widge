$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Watcher = Join-Path $ScriptDir "codex_quota_watcher.py"
$TaskName = "Codex Quota Widget Watcher"

if (Get-Command pythonw.exe -ErrorAction SilentlyContinue) {
    $Python = (Get-Command pythonw.exe).Source
} else {
    $Python = (Get-Command python.exe).Source
}

$Action = New-ScheduledTaskAction -Execute $Python -Argument "`"$Watcher`""
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Days 365)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Starts the Codex quota widget when Codex Desktop is running." -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host "Installed and started: $TaskName"
