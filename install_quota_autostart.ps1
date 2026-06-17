$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Widget = Join-Path $ScriptDir "codex_quota_widget.py"
$Exe = Join-Path $ScriptDir "CodexQuotaWidget.exe"
$TaskName = "Codex Quota Widget Watcher"

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

if (Test-Path $Exe) {
    $Execute = $Exe
    $Arguments = "--watcher"
} elseif (Get-Command pythonw.exe -ErrorAction SilentlyContinue) {
    $Execute = (Get-Command pythonw.exe).Source
    $Arguments = "`"$Widget`" --watcher"
} else {
    $Execute = (Get-Command python.exe).Source
    $Arguments = "`"$Widget`" --watcher"
}

$Action = New-ScheduledTaskAction -Execute $Execute -Argument $Arguments
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Days 365) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Starts the Codex quota widget when Codex Desktop is running." -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host "Installed and started: $TaskName"
