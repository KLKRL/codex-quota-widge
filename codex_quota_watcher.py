import subprocess
import sys
import time
from pathlib import Path


HERE = Path(__file__).resolve().parent
WIDGET = HERE / "codex_quota_widget.py"
POLL_SECONDS = 5


def powershell(command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def is_desktop_codex_running() -> bool:
    command = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -ieq 'Codex.exe' -and $_.ExecutablePath -like '*WindowsApps*OpenAI.Codex*' } | "
        "Select-Object -First 1 -ExpandProperty ProcessId"
    )
    return bool(powershell(command).stdout.strip())


def is_widget_running() -> bool:
    command = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -match '^pythonw?\\.exe$' -and $_.CommandLine -like '*codex_quota_widget.py*' } | "
        "Select-Object -First 1 -ExpandProperty ProcessId"
    )
    return bool(powershell(command).stdout.strip())


def pythonw_path() -> str:
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    return str(candidate if candidate.exists() else exe)


def start_widget() -> None:
    if is_widget_running():
        return
    subprocess.Popen([pythonw_path(), str(WIDGET)], close_fds=True)


def stop_widget() -> None:
    command = (
        "$targets = Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -match '^pythonw?\\.exe$' -and $_.CommandLine -like '*codex_quota_widget.py*' }; "
        "foreach ($p in $targets) { Stop-Process -Id $p.ProcessId -Force }"
    )
    powershell(command)


def main() -> None:
    while True:
        if is_desktop_codex_running():
            start_widget()
        else:
            stop_widget()
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
