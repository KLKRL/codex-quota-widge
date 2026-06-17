$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Widget = Join-Path $ScriptDir "codex_quota_widget.py"
$Exe = Join-Path $ScriptDir "CodexQuotaWidget.exe"

if (Test-Path $Exe) {
    Start-Process $Exe
} elseif (Get-Command pythonw.exe -ErrorAction SilentlyContinue) {
    Start-Process pythonw.exe -ArgumentList @($Widget, "--widget")
} else {
    Start-Process python.exe -ArgumentList @($Widget, "--widget")
}
