import subprocess
import sys
from pathlib import Path


WIDGET = Path(__file__).resolve().with_name("codex_quota_widget.py")


def main() -> None:
    subprocess.call([sys.executable, str(WIDGET), "--watcher"])


if __name__ == "__main__":
    main()
