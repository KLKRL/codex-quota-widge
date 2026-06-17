$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Widget = Join-Path $ScriptDir "codex_quota_widget.py"

if (Get-Command pythonw.exe -ErrorAction SilentlyContinue) {
    Start-Process pythonw.exe -ArgumentList @($Widget)
} else {
    Start-Process python.exe -ArgumentList @($Widget)
}
