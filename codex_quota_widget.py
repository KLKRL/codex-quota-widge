import argparse
import glob
import json
import os
import time
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

from PIL import Image, ImageDraw, ImageTk


APP_NAME = "Codex Quota"
CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
SETTINGS_DIR = Path("D:/Codex/quota_widget")
SETTINGS_PATH = SETTINGS_DIR / "settings.json"
REFRESH_MS = 30_000
WINDOW_W = 350
WINDOW_H = 164

THEME = {
    "bg": "#FFF9FB",
    "header": "#FFE4EF",
    "card": "#FFF9FB",
    "border": "#EFA9C0",
    "track": "#F5D8E3",
    "primary": "#EC4899",
    "secondary": "#F43F5E",
    "text": "#4C1D35",
    "muted": "#9E7685",
    "quiet": "#C19AAA",
    "menu_hover": "#FFE4EF",
}


@dataclass
class LimitInfo:
    used: float | None
    remaining: float | None
    resets_at: int | None


@dataclass
class QuotaSnapshot:
    primary: LimitInfo
    secondary: LimitInfo
    plan_type: str | None
    source_file: str | None
    source_timestamp: str | None


def read_settings() -> dict:
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_settings(settings: dict) -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def iter_candidate_logs() -> list[Path]:
    patterns = [
        CODEX_HOME / "sessions" / "**" / "*.jsonl",
        CODEX_HOME / "archived_sessions" / "*.jsonl",
    ]
    files: list[Path] = []
    for pattern in patterns:
        files.extend(Path(p) for p in glob.glob(str(pattern), recursive=True))
    files = [p for p in files if p.is_file()]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def tail_text(path: Path, max_bytes: int = 2_000_000) -> str:
    size = path.stat().st_size
    with path.open("rb") as f:
        if size > max_bytes:
            f.seek(-max_bytes, os.SEEK_END)
        data = f.read()
    return data.decode("utf-8", errors="replace")


def parse_limit(raw: dict | None) -> LimitInfo:
    if not isinstance(raw, dict):
        return LimitInfo(None, None, None)
    used = raw.get("used_percent")
    try:
        used_num = float(used)
    except (TypeError, ValueError):
        used_num = None
    remaining = None if used_num is None else max(0.0, min(100.0, 100.0 - used_num))
    resets_at = raw.get("resets_at")
    try:
        resets_at_num = int(resets_at) if resets_at is not None else None
    except (TypeError, ValueError):
        resets_at_num = None
    return LimitInfo(used_num, remaining, resets_at_num)


def find_latest_snapshot() -> QuotaSnapshot | None:
    for path in iter_candidate_logs():
        try:
            text = tail_text(path)
        except OSError:
            continue
        lines = [line for line in text.splitlines() if '"rate_limits"' in line]
        for line in reversed(lines):
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            limits = item.get("rate_limits")
            if not isinstance(limits, dict):
                payload = item.get("payload")
                if isinstance(payload, dict):
                    limits = payload.get("rate_limits")
            if not isinstance(limits, dict):
                continue
            return QuotaSnapshot(
                primary=parse_limit(limits.get("primary")),
                secondary=parse_limit(limits.get("secondary")),
                plan_type=limits.get("plan_type"),
                source_file=str(path),
                source_timestamp=item.get("timestamp"),
            )
    return None


def fmt_percent(value: float | None) -> str:
    if value is None:
        return "--%"
    return f"{value:.0f}%"


def fmt_datetime(timestamp: int | None) -> str:
    if timestamp is None:
        return "--"
    return datetime.fromtimestamp(timestamp).strftime("%m-%d %H:%M")


def fmt_age(iso_ts: str | None) -> str:
    if not iso_ts:
        return "--"
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        delta = max(0, int(time.time() - dt.timestamp()))
    except ValueError:
        return "--"
    if delta < 60:
        return f"{delta}s ago"
    if delta < 3600:
        return f"{delta // 60}m ago"
    return f"{delta // 3600}h ago"


def status_color(remaining: float | None) -> str:
    if remaining is None:
        return THEME["quiet"]
    if remaining <= 20:
        return "#E11D48"
    if remaining <= 40:
        return "#F9739B"
    return "#BE185D"


class QuotaWidget:
    def __init__(self) -> None:
        self.settings = read_settings()
        self.topmost = bool(self.settings.get("topmost", True))
        self.menu_window: tk.Toplevel | None = None
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", self.topmost)
        self.root.configure(bg=THEME["card"])
        self.root.resizable(False, False)

        x = int(self.settings.get("x", self.root.winfo_screenwidth() - WINDOW_W - 40))
        y = int(self.settings.get("y", 90))
        self.root.geometry(f"{WINDOW_W}x{WINDOW_H}+{x}+{y}")

        self.canvas = tk.Canvas(self.root, width=WINDOW_W, height=WINDOW_H, bg=THEME["card"], highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.drag_offset = (0, 0)
        self.snapshot: QuotaSnapshot | None = None
        self.image_refs: list[ImageTk.PhotoImage] = []

        for widget in (self.root, self.canvas):
            widget.bind("<ButtonPress-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.on_drag)
            widget.bind("<ButtonRelease-1>", self.end_drag)
            widget.bind("<Button-3>", self.show_menu)

        self.refresh()
        self.root.after(REFRESH_MS, self.periodic_refresh)

    def rounded_rect(self, x1: int, y1: int, x2: int, y2: int, r: int, fill: str, outline: str = "") -> None:
        self.canvas.create_arc(x1, y1, x1 + 2 * r, y1 + 2 * r, start=90, extent=90, fill=fill, outline=outline)
        self.canvas.create_arc(x2 - 2 * r, y1, x2, y1 + 2 * r, start=0, extent=90, fill=fill, outline=outline)
        self.canvas.create_arc(x2 - 2 * r, y2 - 2 * r, x2, y2, start=270, extent=90, fill=fill, outline=outline)
        self.canvas.create_arc(x1, y2 - 2 * r, x1 + 2 * r, y2, start=180, extent=90, fill=fill, outline=outline)
        self.canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline=outline)
        self.canvas.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline=outline)

    def progress_bar(self, x: int, y: int, width: int, value: float | None, color: str) -> None:
        height = 8
        scale = 4
        image = Image.new("RGBA", (width * scale, height * scale), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        radius = height * scale // 2
        draw.rounded_rectangle(
            (0, 0, width * scale - 1, height * scale - 1),
            radius=radius,
            fill=THEME["track"],
        )
        if value is not None:
            filled = int(width * scale * max(0.0, min(100.0, value)) / 100)
            if filled > 0:
                draw.rounded_rectangle(
                    (0, 0, max(filled, radius * 2) - 1, height * scale - 1),
                    radius=radius,
                    fill=color,
                )
                if filled < radius * 2:
                    draw.rectangle((filled, 0, radius * 2, height * scale), fill=THEME["track"])
        image = image.resize((width, height), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(image)
        self.image_refs.append(photo)
        self.canvas.create_image(x, y, image=photo, anchor="nw")

    def pill(self, x: int, y: int, width: int, height: int, fill: str) -> None:
        scale = 4
        image = Image.new("RGBA", (width * scale, height * scale), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (0, 0, width * scale - 1, height * scale - 1),
            radius=height * scale // 2,
            fill=fill,
        )
        image = image.resize((width, height), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(image)
        self.image_refs.append(photo)
        self.canvas.create_image(x, y, image=photo, anchor="nw")

    def draw_limit(self, y: int, title: str, limit: LimitInfo) -> None:
        color = status_color(limit.remaining)
        self.canvas.create_text(24, y, anchor="w", text=title, fill=THEME["text"], font=("Microsoft YaHei UI", 10, "bold"))
        self.canvas.create_text(315, y - 4, anchor="e", text=fmt_percent(limit.remaining), fill=color, font=("Segoe UI", 20, "bold"))
        self.progress_bar(104, y + 5, 154, limit.remaining, color)

    def redraw(self) -> None:
        self.canvas.delete("all")
        self.image_refs.clear()
        self.canvas.create_rectangle(0, 0, WINDOW_W, WINDOW_H, fill=THEME["card"], outline=THEME["card"])
        self.canvas.create_rectangle(0, 0, WINDOW_W, 58, fill=THEME["header"], outline=THEME["header"])

        self.canvas.create_text(24, 32, anchor="w", text="Codex Quota", fill=THEME["text"], font=("Segoe UI", 16, "bold"))
        plan = self.snapshot.plan_type if self.snapshot else "offline"
        self.pill(284, 23, 36, 18, "#FFFFFF")
        self.canvas.create_text(302, 32, anchor="center", text=str(plan).upper(), fill="#BE185D", font=("Segoe UI", 8, "bold"))

        if self.snapshot is None:
            self.canvas.create_text(175, 96, text="等待 Codex 写入额度日志", fill=THEME["text"], font=("Microsoft YaHei UI", 11))
            self.canvas.create_text(175, 123, text="右键可以手动刷新", fill=THEME["muted"], font=("Microsoft YaHei UI", 9))
            return

        self.draw_limit(82, "五小时", self.snapshot.primary)
        self.draw_limit(114, "周额度", self.snapshot.secondary)
        self.canvas.create_text(
            24,
            146,
            anchor="w",
            text=(
                f"五小时 {fmt_datetime(self.snapshot.primary.resets_at)} · "
                f"周额 {fmt_datetime(self.snapshot.secondary.resets_at)}"
            ),
            fill=THEME["muted"],
            font=("Microsoft YaHei UI", 8),
        )

    def refresh(self) -> None:
        self.snapshot = find_latest_snapshot()
        self.redraw()

    def periodic_refresh(self) -> None:
        self.refresh()
        self.root.after(REFRESH_MS, self.periodic_refresh)

    def summary(self) -> str:
        if self.snapshot is None:
            return "Codex Quota: 暂未读到额度日志"
        return (
            f"Codex Quota: 五小时剩余 {fmt_percent(self.snapshot.primary.remaining)}, "
            f"周额度剩余 {fmt_percent(self.snapshot.secondary.remaining)}, "
            f"五小时刷新 {fmt_datetime(self.snapshot.primary.resets_at)}, "
            f"周额度刷新 {fmt_datetime(self.snapshot.secondary.resets_at)}"
        )

    def copy_summary(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.summary())

    def toggle_topmost(self) -> None:
        self.topmost = not self.topmost
        self.root.attributes("-topmost", self.topmost)
        self.settings["topmost"] = self.topmost
        write_settings(self.settings)

    def show_menu(self, event: tk.Event) -> None:
        self.close_menu()
        self.menu_window = tk.Toplevel(self.root)
        self.menu_window.overrideredirect(True)
        self.menu_window.attributes("-topmost", True)
        self.menu_window.configure(bg=THEME["card"])
        self.menu_window.geometry(f"112x132+{event.x_root}+{event.y_root}")
        canvas = tk.Canvas(self.menu_window, width=112, height=132, bg=THEME["card"], highlightthickness=0)
        canvas.pack(fill="both", expand=True)

        def menu_rect(x1: int, y1: int, x2: int, y2: int, r: int, fill: str, outline: str = "") -> None:
            canvas.create_arc(x1, y1, x1 + 2 * r, y1 + 2 * r, start=90, extent=90, fill=fill, outline=outline)
            canvas.create_arc(x2 - 2 * r, y1, x2, y1 + 2 * r, start=0, extent=90, fill=fill, outline=outline)
            canvas.create_arc(x2 - 2 * r, y2 - 2 * r, x2, y2, start=270, extent=90, fill=fill, outline=outline)
            canvas.create_arc(x1, y2 - 2 * r, x1 + 2 * r, y2, start=180, extent=90, fill=fill, outline=outline)
            canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline=outline)
            canvas.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline=outline)

        canvas.create_rectangle(0, 0, 112, 132, fill=THEME["card"], outline=THEME["card"])
        menu_rect(8, 8, 104, 33, 7, THEME["menu_hover"])
        canvas.create_line(14, 88, 98, 88, fill=THEME["border"])

        actions = [
            ("重新读取", self.refresh, True),
            ("复制摘要", self.copy_summary, False),
            ("切换置顶", self.toggle_topmost, False),
            ("退出", self.close, False),
        ]
        for index, (label, action, strong) in enumerate(actions):
            y = 20 + index * 28
            color = "#BE185D" if strong else THEME["text"]
            row_color = THEME["menu_hover"] if index == 0 else THEME["card"]
            canvas.create_rectangle(8, y - 12, 104, y + 12, outline="", fill=row_color, tags=(f"row{index}", f"hit{index}"))
            canvas.create_text(
                18,
                y,
                anchor="w",
                text=label,
                fill=color,
                font=("Microsoft YaHei UI", 9, "bold" if strong else "normal"),
                tags=(f"hit{index}",),
            )
            canvas.tag_bind(f"hit{index}", "<Button-1>", lambda _e, cmd=action: self.menu_action(cmd))
            canvas.tag_bind(f"hit{index}", "<Enter>", lambda _e, i=index, c=canvas: self.highlight_menu(c, i))
        self.menu_window.bind("<FocusOut>", lambda _e: self.close_menu())
        self.menu_window.after(100, self.menu_window.focus_force)

    def highlight_menu(self, canvas: tk.Canvas, index: int) -> None:
        for row_index in range(4):
            canvas.itemconfigure(f"row{row_index}", fill=THEME["card"])
        canvas.itemconfigure(f"row{index}", fill=THEME["menu_hover"])

    def menu_action(self, action) -> None:
        self.close_menu()
        action()

    def close_menu(self) -> None:
        if self.menu_window is not None and self.menu_window.winfo_exists():
            self.menu_window.destroy()
        self.menu_window = None

    def start_drag(self, event: tk.Event) -> None:
        self.drag_offset = (event.x, event.y)

    def on_drag(self, event: tk.Event) -> None:
        x = event.x_root - self.drag_offset[0]
        y = event.y_root - self.drag_offset[1]
        self.root.geometry(f"+{x}+{y}")

    def end_drag(self, _event: tk.Event) -> None:
        self.settings["x"] = self.root.winfo_x()
        self.settings["y"] = self.root.winfo_y()
        self.settings["topmost"] = self.topmost
        write_settings(self.settings)

    def close(self) -> None:
        self.close_menu()
        self.end_drag(None)  # type: ignore[arg-type]
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Codex quota desktop widget")
    parser.add_argument("--once", action="store_true", help="print the latest quota snapshot and exit")
    args = parser.parse_args()

    if args.once:
        snapshot = find_latest_snapshot()
        if snapshot is None:
            print(json.dumps({"ok": False, "error": "no rate_limits found"}, ensure_ascii=False))
            return
        print(json.dumps({
            "ok": True,
            "primary_remaining": snapshot.primary.remaining,
            "secondary_remaining": snapshot.secondary.remaining,
            "primary_resets": fmt_datetime(snapshot.primary.resets_at),
            "secondary_resets": fmt_datetime(snapshot.secondary.resets_at),
            "plan_type": snapshot.plan_type,
            "source_timestamp": snapshot.source_timestamp,
            "source_file": snapshot.source_file,
        }, ensure_ascii=False, indent=2))
        return

    try:
        QuotaWidget().run()
    except Exception as exc:
        messagebox.showerror(APP_NAME, str(exc))


if __name__ == "__main__":
    main()
