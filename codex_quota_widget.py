import argparse
import base64
import glob
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
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
SCALE_OPTIONS = [0.85, 1.0, 1.15, 1.3]
USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
CREDITS_URL = "https://chatgpt.com/backend-api/wham/rate-limit-reset-credits"
MAX_AUTH_BYTES = 256 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024

THEME_ORDER = ["berry", "cream", "sakura", "mint", "sky", "dark"]
THEMES = {
    "berry": {
        "label": "莓果白",
        "header": "#FFE4EF",
        "card": "#FFF9FB",
        "border": "#EFA9C0",
        "track": "#F5D8E3",
        "primary": "#EC4899",
        "secondary": "#BE185D",
        "text": "#4C1D35",
        "muted": "#9E7685",
        "quiet": "#C19AAA",
        "menu_hover": "#FFE4EF",
        "pill": "#FFFFFF",
    },
    "cream": {
        "label": "奶油粉",
        "header": "#FFF0F5",
        "card": "#FFFBFC",
        "border": "#F4C6D6",
        "track": "#F4E5EA",
        "primary": "#F472B6",
        "secondary": "#C02662",
        "text": "#3B2430",
        "muted": "#9B7A87",
        "quiet": "#B994A2",
        "menu_hover": "#FCE7F3",
        "pill": "#FFFFFF",
    },
    "sakura": {
        "label": "樱花",
        "header": "#FFF1F6",
        "card": "#FFFFFF",
        "border": "#F2C4D1",
        "track": "#F2E8EE",
        "primary": "#F9A8D4",
        "secondary": "#DB2777",
        "text": "#34242B",
        "muted": "#8E7580",
        "quiet": "#B096A3",
        "menu_hover": "#FFF1F6",
        "pill": "#FFF8FB",
    },
    "mint": {
        "label": "薄荷",
        "header": "#E8FFF5",
        "card": "#FBFFFD",
        "border": "#B7E7D0",
        "track": "#DDEFE7",
        "primary": "#34D399",
        "secondary": "#059669",
        "text": "#173B2C",
        "muted": "#638074",
        "quiet": "#8AA99C",
        "menu_hover": "#E8FFF5",
        "pill": "#FFFFFF",
    },
    "sky": {
        "label": "天空",
        "header": "#EAF5FF",
        "card": "#FBFDFF",
        "border": "#BFDDF6",
        "track": "#DCEAF6",
        "primary": "#60A5FA",
        "secondary": "#2563EB",
        "text": "#1E2E46",
        "muted": "#64758C",
        "quiet": "#8EA2B8",
        "menu_hover": "#EAF5FF",
        "pill": "#FFFFFF",
    },
    "dark": {
        "label": "夜粉",
        "header": "#241722",
        "card": "#151217",
        "border": "#3C2635",
        "track": "#302632",
        "primary": "#F472B6",
        "secondary": "#EC4899",
        "text": "#FFF1F6",
        "muted": "#C9A9B8",
        "quiet": "#8D7180",
        "menu_hover": "#312032",
        "pill": "#2B1E29",
    },
}
THEME = dict(THEMES["berry"])


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
    limit_id: str | None = None
    credits_exhausted: bool = False
    reset_credits: int | None = None
    reset_credit_expires_at: list[int] | None = None
    status: str = "ok"
    message: str | None = None
    stale: bool = False


def popen_no_window() -> int:
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def read_settings() -> dict:
    for path in [SETTINGS_PATH, SETTINGS_PATH.with_suffix(".bak")]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def write_settings(settings: dict) -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(settings, ensure_ascii=False, indent=2)
    tmp_path = SETTINGS_PATH.with_suffix(".tmp")
    bak_path = SETTINGS_PATH.with_suffix(".bak")
    tmp_path.write_text(raw, encoding="utf-8")
    if SETTINGS_PATH.exists():
        try:
            SETTINGS_PATH.replace(bak_path)
        except OSError:
            pass
    tmp_path.replace(SETTINGS_PATH)


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
    used = raw.get("used_percent", raw.get("usedPercent"))
    try:
        used_num = float(used)
    except (TypeError, ValueError):
        used_num = None
    remaining = None if used_num is None else max(0.0, min(100.0, 100.0 - used_num))
    resets_at = raw.get("resets_at", raw.get("resetsAt"))
    try:
        resets_at_num = int(resets_at) if resets_at is not None else None
    except (TypeError, ValueError):
        resets_at_num = None
    return LimitInfo(used_num, remaining, resets_at_num)


def pick_string(value: dict, keys: list[str]) -> str | None:
    for key in keys:
        item = value.get(key)
        if isinstance(item, str) and item:
            return item
    return None


def account_id_from_jwt(token: str) -> str | None:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        raw = base64.urlsafe_b64decode(payload.encode("ascii"))
        value = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    if not isinstance(value, dict):
        return None
    return pick_string(value, ["https://api.openai.com/auth.chatgpt_account_id", "chatgpt_account_id"])


def load_auth() -> tuple[str, str | None] | None:
    auth_path = CODEX_HOME / "auth.json"
    try:
        if not auth_path.is_file() or auth_path.stat().st_size > MAX_AUTH_BYTES:
            return None
        value = json.loads(auth_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(value, dict):
        return None
    tokens = value.get("tokens")
    if not isinstance(tokens, dict):
        tokens = value
    access_token = pick_string(tokens, ["access_token", "accessToken"])
    if not access_token:
        return None
    account_id = (
        pick_string(tokens, ["account_id", "accountId"])
        or pick_string(value, ["account_id", "accountId"])
        or account_id_from_jwt(access_token)
    )
    return access_token, account_id


def request_json(url: str, headers: dict[str, str], timeout_sec: float) -> dict | list | None:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            length = response.headers.get("Content-Length")
            if length is not None and int(length) > MAX_RESPONSE_BYTES:
                return None
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return None
        return None
    except Exception:
        return None
    if len(raw) > MAX_RESPONSE_BYTES:
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    return value if isinstance(value, (dict, list)) else None


def number_with_key(value: dict, keys: list[str]) -> tuple[str, float] | None:
    for key in keys:
        item = value.get(key)
        if isinstance(item, (int, float)):
            return key, float(item)
        if isinstance(item, str):
            try:
                return key, float(item)
            except ValueError:
                pass
    return None


def integer(value: dict | None, keys: list[str]) -> int | None:
    if not isinstance(value, dict):
        return None
    for key in keys:
        item = value.get(key)
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            return item
        if isinstance(item, float) and item.is_integer():
            return int(item)
        if isinstance(item, str):
            try:
                return int(float(item))
            except ValueError:
                pass
    return None


def timestamp_epoch(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value:
        try:
            return int(float(value))
        except ValueError:
            pass
        try:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
        except ValueError:
            return None
    return None


def timestamp_from_keys(value: dict, keys: list[str]) -> int | None:
    for key in keys:
        result = timestamp_epoch(value.get(key))
        if result is not None:
            return result
    return None


def scale_ratio_field(key: str, value: float) -> bool:
    return key in {"remaining_ratio", "remainingRatio", "used_ratio", "usedRatio", "utilization"} or (
        "percent" not in key.lower() and "pct" not in key.lower() and value <= 1.0
    )


def parse_usage_window(raw: object) -> LimitInfo:
    if not isinstance(raw, dict):
        return LimitInfo(None, None, None)
    remaining_pair = number_with_key(
        raw,
        [
            "remaining_percent",
            "remainingPercent",
            "remaining_pct",
            "remainingPct",
            "remaining_ratio",
            "remainingRatio",
            "remaining",
        ],
    )
    used_num = None
    if remaining_pair is not None:
        key, remaining = remaining_pair
        remaining_num = remaining * 100.0 if scale_ratio_field(key, remaining) else remaining
    else:
        used_pair = number_with_key(
            raw,
            [
                "used_percent",
                "usedPercent",
                "used_pct",
                "usedPct",
                "used_ratio",
                "usedRatio",
                "utilization",
                "used",
            ],
        )
        if used_pair is None:
            return LimitInfo(None, None, timestamp_from_keys(raw, ["reset_at", "resetAt", "resets_at", "resetsAt", "reset_time", "resetTime"]))
        key, used = used_pair
        used_num = used * 100.0 if scale_ratio_field(key, used) else used
        remaining_num = 100.0 - used_num
    remaining_num = max(0.0, min(100.0, remaining_num))
    if used_num is None:
        used_num = 100.0 - remaining_num
    return LimitInfo(
        used=max(0.0, min(100.0, used_num)),
        remaining=remaining_num,
        resets_at=timestamp_from_keys(raw, ["reset_at", "resetAt", "resets_at", "resetsAt", "reset_time", "resetTime"]),
    )


def window_seconds(raw: dict) -> int | None:
    return integer(
        raw,
        [
            "limit_window_seconds",
            "limitWindowSeconds",
            "window_seconds",
            "windowSeconds",
            "duration_seconds",
            "durationSeconds",
            "period_seconds",
            "periodSeconds",
        ],
    )


def find_window(rate_limit: object, names: list[str], expected_seconds: int) -> object | None:
    if not isinstance(rate_limit, dict):
        return None
    lower_names = [name.lower() for name in names]
    for name in names:
        value = rate_limit.get(name)
        if isinstance(value, dict) and parse_usage_window(value).remaining is not None:
            return value
    for key in ["windows", "limit_windows", "limitWindows", "limits", "buckets"]:
        items = rate_limit.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict) or parse_usage_window(item).remaining is None:
                continue
            duration = window_seconds(item)
            matches_duration = duration is not None and abs(duration - expected_seconds) <= 60
            label = pick_string(item, ["name", "type", "id", "window", "label"])
            matches_name = False
            if label:
                text = label.lower()
                matches_name = any(text == name or name in text for name in lower_names)
            if matches_duration or matches_name:
                return item
    return None


def collect_reset_credit_expirations(value: object) -> list[int]:
    result: set[int] = set()

    def visit(item: object) -> None:
        if isinstance(item, list):
            for child in item:
                visit(child)
            return
        if not isinstance(item, dict):
            return
        expires_at = timestamp_from_keys(item, ["expires_at", "expiresAt", "expiration_time", "expirationTime", "expires"])
        if expires_at is not None:
            result.add(expires_at)
        for key in ["credits", "reset_credits", "resetCredits", "available", "items", "grants"]:
            if key in item:
                visit(item[key])

    visit(value)
    return sorted(result)


def parse_credit_count(value: object) -> int | None:
    if isinstance(value, dict):
        return integer(value, ["available_count", "availableCount", "remaining", "count", "quantity"])
    return None


def read_wham_snapshot(timeout_sec: float = 12.0) -> QuotaSnapshot | None:
    auth = load_auth()
    if auth is None:
        return None
    access_token, account_id = auth
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "originator": "Codex Desktop",
        "OAI-Product-Sku": "CODEX",
        "User-Agent": "CodexQuotaWidget/0.2",
    }
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id

    usage = request_json(USAGE_URL, headers, timeout_sec)
    if not isinstance(usage, dict):
        return None
    rate_limit = usage.get("rate_limit") or usage.get("rateLimit") or usage
    primary = parse_usage_window(
        find_window(
            rate_limit,
            ["primary_window", "primaryWindow", "short_window", "shortWindow", "five_hour_window", "fiveHourWindow", "5h", "primary"],
            18_000,
        )
    )
    secondary = parse_usage_window(
        find_window(
            rate_limit,
            ["secondary_window", "secondaryWindow", "weekly_window", "weeklyWindow", "week_window", "weekWindow", "weekly", "secondary"],
            604_800,
        )
    )
    if primary.remaining is None and secondary.remaining is None:
        return None

    usage_credits = usage.get("rate_limit_reset_credits") or usage.get("rateLimitResetCredits")
    reset_credits = parse_credit_count(usage_credits)
    expires_at = collect_reset_credit_expirations(usage_credits)

    credits = request_json(CREDITS_URL, headers, timeout_sec)
    if isinstance(credits, dict):
        reset_credits = parse_credit_count(credits) if parse_credit_count(credits) is not None else reset_credits
        credit_expires_at = collect_reset_credit_expirations(credits)
        if credit_expires_at:
            expires_at = credit_expires_at

    return QuotaSnapshot(
        primary=primary,
        secondary=secondary,
        plan_type=pick_string(usage, ["plan_type", "planType"]) or "codex",
        source_file="chatgpt.com/backend-api/wham/usage",
        source_timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        limit_id="codex",
        reset_credits=reset_credits,
        reset_credit_expires_at=expires_at,
    )


def likely_stale_rebound(previous: QuotaSnapshot | None, current: QuotaSnapshot | None) -> bool:
    if previous is None or current is None:
        return False
    if previous.primary.remaining is None or current.primary.remaining is None:
        return False
    same_reset = previous.primary.resets_at is not None and previous.primary.resets_at == current.primary.resets_at
    if not same_reset:
        return False
    if previous.reset_credits != current.reset_credits:
        return False
    return current.primary.remaining - previous.primary.remaining >= 25


def find_codex_cli() -> Path | None:
    env_cli = os.environ.get("CODEX_CLI")
    if env_cli:
        path = Path(env_cli)
        if path.exists():
            return path
    local_root = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI" / "Codex" / "bin"
    candidates = sorted(local_root.glob("*/codex.exe"), key=lambda p: p.stat().st_mtime, reverse=True)
    if candidates:
        return candidates[0]
    return None


def read_live_snapshot(timeout_sec: float = 15.0) -> QuotaSnapshot | None:
    cli = find_codex_cli()
    if cli is None:
        return None

    proc = subprocess.Popen(
        [str(cli), "app-server", "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=popen_no_window(),
    )
    output: queue.Queue[str] = queue.Queue()

    def read_stdout() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            output.put(line)

    threading.Thread(target=read_stdout, daemon=True).start()

    def send(message: dict) -> None:
        if proc.stdin is None:
            raise RuntimeError("Codex app-server stdin is closed")
        proc.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        proc.stdin.flush()

    try:
        send({
            "id": 1,
            "method": "initialize",
            "params": {
                "clientInfo": {"name": "quota-widget", "title": "Codex Quota Widget", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True, "requestAttestation": False, "optOutNotificationMethods": []},
            },
        })
        send({"id": 2, "method": "account/rateLimits/read"})

        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            try:
                line = output.get(timeout=0.2)
            except queue.Empty:
                if proc.poll() is not None:
                    break
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("id") != 2:
                continue
            result = item.get("result")
            if not isinstance(result, dict):
                return None
            by_limit = result.get("rateLimitsByLimitId")
            limits = None
            if isinstance(by_limit, dict):
                limits = by_limit.get("codex")
            if not isinstance(limits, dict):
                limits = result.get("rateLimits")
            if not isinstance(limits, dict):
                return None
            primary = parse_limit(limits.get("primary"))
            secondary = parse_limit(limits.get("secondary"))
            if primary.used is None and secondary.used is None:
                return None
            credits = limits.get("credits")
            return QuotaSnapshot(
                primary=primary,
                secondary=secondary,
                plan_type=limits.get("planType") or limits.get("plan_type"),
                source_file="codex app-server account/rateLimits/read",
                source_timestamp=datetime.now().isoformat(timespec="seconds"),
                limit_id=limits.get("limitId") or limits.get("limit_id"),
                credits_exhausted=isinstance(credits, dict) and credits.get("hasCredits", credits.get("has_credits")) is False,
            )
    except Exception:
        return None
    finally:
        try:
            if proc.stdin is not None:
                proc.stdin.close()
        except Exception:
            pass
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()


def read_quota_snapshot(previous: QuotaSnapshot | None = None, force: bool = False) -> QuotaSnapshot | None:
    snapshot = read_wham_snapshot(timeout_sec=12.0 if force else 8.0) or read_live_snapshot(timeout_sec=8.0) or find_latest_snapshot()
    if likely_stale_rebound(previous, snapshot):
        assert previous is not None
        previous.stale = True
        previous.message = "数据可能未同步，暂时保留上一次较低额度"
        previous.source_timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return previous
    return snapshot


def find_latest_snapshot() -> QuotaSnapshot | None:
    latest: tuple[str, QuotaSnapshot] | None = None
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
            if limits.get("limit_id") != "codex":
                continue
            primary = parse_limit(limits.get("primary"))
            secondary = parse_limit(limits.get("secondary"))
            if primary.used is None and secondary.used is None:
                continue
            credits = limits.get("credits")
            timestamp = item.get("timestamp")
            if not isinstance(timestamp, str):
                continue
            snapshot = QuotaSnapshot(
                primary=primary,
                secondary=secondary,
                plan_type=limits.get("plan_type"),
                source_file=str(path),
                source_timestamp=timestamp,
                limit_id=limits.get("limit_id"),
                credits_exhausted=isinstance(credits, dict) and credits.get("has_credits") is False,
            )
            if latest is None or timestamp > latest[0]:
                latest = (timestamp, snapshot)
    return latest[1] if latest is not None else None


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


def status_color(remaining: float | None, theme: dict | None = None) -> str:
    active = theme or THEME
    if remaining is None:
        return active["quiet"]
    if remaining <= 20:
        return "#E11D48"
    if remaining <= 40:
        return active["primary"]
    return active["secondary"]


class QuotaWidget:
    def __init__(self) -> None:
        self.settings = read_settings()
        self.topmost = bool(self.settings.get("topmost", True))
        self.scale = float(self.settings.get("scale", 1.0))
        if self.scale not in SCALE_OPTIONS:
            self.scale = 1.0
        self.theme_name = self.settings.get("theme", "berry")
        if self.theme_name not in THEMES:
            self.theme_name = "berry"
        self.theme = dict(THEMES[self.theme_name])
        self.menu_window: tk.Toplevel | None = None
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", self.topmost)
        self.root.configure(bg=self.theme["card"])
        self.root.resizable(False, False)

        self.window_w = int(WINDOW_W * self.scale)
        self.window_h = int(WINDOW_H * self.scale)
        x = int(self.settings.get("x", self.root.winfo_screenwidth() - self.window_w - 40))
        y = int(self.settings.get("y", 90))
        self.root.geometry(f"{self.window_w}x{self.window_h}+{x}+{y}")

        self.canvas = tk.Canvas(self.root, width=self.window_w, height=self.window_h, bg=self.theme["card"], highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.drag_offset = (0, 0)
        self.snapshot: QuotaSnapshot | None = None
        self.image_refs: list[ImageTk.PhotoImage] = []
        self.fetching = False
        self.pending_force_refresh = False

        for widget in (self.root, self.canvas):
            widget.bind("<ButtonPress-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.on_drag)
            widget.bind("<ButtonRelease-1>", self.end_drag)
            widget.bind("<Button-3>", self.show_menu)

        self.redraw()
        self.refresh()
        self.root.after(REFRESH_MS, self.periodic_refresh)

    def v(self, value: float) -> int:
        return int(round(value * self.scale))

    def font(self, family: str, size: int, weight: str = "normal") -> tuple[str, int, str]:
        return (family, max(7, int(round(size * self.scale))), weight)

    def text(self, x: int, y: int, **kwargs) -> None:
        self.canvas.create_text(self.v(x), self.v(y), **kwargs)

    def rect(self, x1: int, y1: int, x2: int, y2: int, **kwargs) -> None:
        self.canvas.create_rectangle(self.v(x1), self.v(y1), self.v(x2), self.v(y2), **kwargs)

    def rounded_rect(self, x1: int, y1: int, x2: int, y2: int, r: int, fill: str, outline: str = "") -> None:
        x1, y1, x2, y2, r = self.v(x1), self.v(y1), self.v(x2), self.v(y2), self.v(r)
        self.canvas.create_arc(x1, y1, x1 + 2 * r, y1 + 2 * r, start=90, extent=90, fill=fill, outline=outline)
        self.canvas.create_arc(x2 - 2 * r, y1, x2, y1 + 2 * r, start=0, extent=90, fill=fill, outline=outline)
        self.canvas.create_arc(x2 - 2 * r, y2 - 2 * r, x2, y2, start=270, extent=90, fill=fill, outline=outline)
        self.canvas.create_arc(x1, y2 - 2 * r, x1 + 2 * r, y2, start=180, extent=90, fill=fill, outline=outline)
        self.canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline=outline)
        self.canvas.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline=outline)

    def progress_bar(self, x: int, y: int, width: int, value: float | None, color: str) -> None:
        height = self.v(8)
        width = self.v(width)
        scale = 4
        image = Image.new("RGBA", (width * scale, height * scale), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        radius = height * scale // 2
        draw.rounded_rectangle(
            (0, 0, width * scale - 1, height * scale - 1),
            radius=radius,
            fill=self.theme["track"],
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
                    draw.rectangle((filled, 0, radius * 2, height * scale), fill=self.theme["track"])
        image = image.resize((width, height), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(image)
        self.image_refs.append(photo)
        self.canvas.create_image(self.v(x), self.v(y), image=photo, anchor="nw")

    def pill(self, x: int, y: int, width: int, height: int, fill: str) -> None:
        width = self.v(width)
        height = self.v(height)
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
        self.canvas.create_image(self.v(x), self.v(y), image=photo, anchor="nw")

    def draw_limit(self, y: int, title: str, limit: LimitInfo) -> None:
        color = status_color(limit.remaining, self.theme)
        self.text(24, y, anchor="w", text=title, fill=self.theme["text"], font=self.font("Microsoft YaHei UI", 10, "bold"))
        self.text(315, y - 4, anchor="e", text=fmt_percent(limit.remaining), fill=color, font=self.font("Segoe UI", 20, "bold"))
        self.progress_bar(104, y + 5, 154, limit.remaining, color)

    def redraw(self) -> None:
        self.canvas.delete("all")
        self.image_refs.clear()
        self.root.configure(bg=self.theme["card"])
        self.canvas.configure(bg=self.theme["card"])
        self.rect(0, 0, WINDOW_W, WINDOW_H, fill=self.theme["card"], outline=self.theme["card"])
        self.rect(0, 0, WINDOW_W, 58, fill=self.theme["header"], outline=self.theme["header"])

        self.text(24, 32, anchor="w", text="Codex Quota", fill=self.theme["text"], font=self.font("Segoe UI", 16, "bold"))
        plan = self.snapshot.plan_type if self.snapshot else "offline"
        self.pill(284, 23, 36, 18, self.theme["pill"])
        self.text(302, 32, anchor="center", text=str(plan).upper(), fill=self.theme["secondary"], font=self.font("Segoe UI", 8, "bold"))

        if self.snapshot is None:
            self.text(175, 96, text="等待 Codex 写入额度日志", fill=self.theme["text"], font=self.font("Microsoft YaHei UI", 11))
            self.text(175, 123, text="右键可以手动刷新", fill=self.theme["muted"], font=self.font("Microsoft YaHei UI", 9))
            return

        self.draw_limit(82, "五小时", self.snapshot.primary)
        self.draw_limit(114, "周额度", self.snapshot.secondary)
        footer = (
            f"五小时 {fmt_datetime(self.snapshot.primary.resets_at)} · "
            f"周额 {fmt_datetime(self.snapshot.secondary.resets_at)}"
        )
        if self.snapshot.reset_credits is not None:
            footer += f" · 重置 {self.snapshot.reset_credits}"
        if self.snapshot.stale:
            footer = "疑似未同步 · " + footer
        self.text(
            24,
            146,
            anchor="w",
            text=footer,
            fill="#E11D48" if self.snapshot.stale else self.theme["muted"],
            font=self.font("Microsoft YaHei UI", 8),
        )

    def refresh(self, force: bool = False) -> None:
        if self.fetching:
            self.pending_force_refresh = self.pending_force_refresh or force
            return
        self.fetching = True
        previous = self.snapshot

        def worker() -> None:
            snapshot = read_quota_snapshot(previous=previous, force=force)
            self.root.after(0, lambda: self.apply_snapshot(snapshot))

        threading.Thread(target=worker, daemon=True).start()

    def apply_snapshot(self, snapshot: QuotaSnapshot | None) -> None:
        if snapshot is not None or self.snapshot is None:
            self.snapshot = snapshot
        self.fetching = False
        self.redraw()
        if self.pending_force_refresh:
            self.pending_force_refresh = False
            self.refresh(force=True)

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
            f"周额度刷新 {fmt_datetime(self.snapshot.secondary.resets_at)}, "
            f"重置次数 {self.snapshot.reset_credits if self.snapshot.reset_credits is not None else '--'}"
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
        self.menu_window.configure(bg=self.theme["card"])
        self.menu_window.geometry(f"132x188+{event.x_root}+{event.y_root}")
        canvas = tk.Canvas(self.menu_window, width=132, height=188, bg=self.theme["card"], highlightthickness=0)
        canvas.pack(fill="both", expand=True)

        def menu_rect(x1: int, y1: int, x2: int, y2: int, r: int, fill: str, outline: str = "") -> None:
            canvas.create_arc(x1, y1, x1 + 2 * r, y1 + 2 * r, start=90, extent=90, fill=fill, outline=outline)
            canvas.create_arc(x2 - 2 * r, y1, x2, y1 + 2 * r, start=0, extent=90, fill=fill, outline=outline)
            canvas.create_arc(x2 - 2 * r, y2 - 2 * r, x2, y2, start=270, extent=90, fill=fill, outline=outline)
            canvas.create_arc(x1, y2 - 2 * r, x1 + 2 * r, y2, start=180, extent=90, fill=fill, outline=outline)
            canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline=outline)
            canvas.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline=outline)

        canvas.create_rectangle(0, 0, 132, 188, fill=self.theme["card"], outline=self.theme["card"])
        menu_rect(8, 8, 124, 33, 7, self.theme["menu_hover"])
        canvas.create_line(14, 144, 118, 144, fill=self.theme["border"])

        actions = [
            ("重新读取", lambda: self.refresh(force=True), True),
            (f"配色: {self.theme['label']}", self.next_theme, True),
            (f"大小: {int(self.scale * 100)}%", self.next_scale, True),
            ("复制摘要", self.copy_summary, False),
            ("切换置顶", self.toggle_topmost, False),
            ("退出", self.close, False),
        ]
        for index, (label, action, strong) in enumerate(actions):
            y = 20 + index * 28
            color = self.theme["secondary"] if strong else self.theme["text"]
            row_color = self.theme["menu_hover"] if index == 0 else self.theme["card"]
            canvas.create_rectangle(8, y - 12, 124, y + 12, outline="", fill=row_color, tags=(f"row{index}", f"hit{index}"))
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
        for row_index in range(6):
            canvas.itemconfigure(f"row{row_index}", fill=self.theme["card"])
        canvas.itemconfigure(f"row{index}", fill=self.theme["menu_hover"])

    def next_theme(self) -> None:
        index = THEME_ORDER.index(self.theme_name)
        self.theme_name = THEME_ORDER[(index + 1) % len(THEME_ORDER)]
        self.theme = dict(THEMES[self.theme_name])
        self.settings["theme"] = self.theme_name
        write_settings(self.settings)
        self.redraw()

    def next_scale(self) -> None:
        index = SCALE_OPTIONS.index(self.scale)
        self.scale = SCALE_OPTIONS[(index + 1) % len(SCALE_OPTIONS)]
        self.settings["scale"] = self.scale
        write_settings(self.settings)
        self.window_w = int(WINDOW_W * self.scale)
        self.window_h = int(WINDOW_H * self.scale)
        self.root.geometry(f"{self.window_w}x{self.window_h}+{self.root.winfo_x()}+{self.root.winfo_y()}")
        self.canvas.configure(width=self.window_w, height=self.window_h)
        self.redraw()

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


def run_powershell(command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True,
        text=True,
        creationflags=popen_no_window(),
    )


def is_desktop_codex_running() -> bool:
    command = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -ieq 'Codex.exe' -and $_.ExecutablePath -like '*WindowsApps*OpenAI.Codex*' } | "
        "Select-Object -First 1 -ExpandProperty ProcessId"
    )
    return bool(run_powershell(command).stdout.strip())


def is_widget_running() -> bool:
    script_name = "codex_quota_widget.py"
    exe_name = "CodexQuotaWidget.exe"
    command = (
        "Get-CimInstance Win32_Process | Where-Object { "
        "($_.Name -match '^pythonw?\\.exe$' -and $_.CommandLine -like '*" + script_name + "*' -and $_.CommandLine -notlike '*--watcher*') "
        "-or ($_.Name -ieq '" + exe_name + "' -and $_.CommandLine -notlike '*--watcher*') "
        "} | Select-Object -First 1 -ExpandProperty ProcessId"
    )
    return bool(run_powershell(command).stdout.strip())


def widget_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--widget"]
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    runner = pythonw if pythonw.exists() else exe
    return [str(runner), str(Path(__file__).resolve()), "--widget"]


def start_widget_process() -> None:
    if is_widget_running():
        return
    subprocess.Popen(widget_command(), close_fds=True, creationflags=popen_no_window())


def stop_widget_processes() -> None:
    command = (
        "$targets = Get-CimInstance Win32_Process | Where-Object { "
        "($_.Name -match '^pythonw?\\.exe$' -and $_.CommandLine -like '*codex_quota_widget.py*' -and $_.CommandLine -notlike '*--watcher*') "
        "-or ($_.Name -ieq 'CodexQuotaWidget.exe' -and $_.CommandLine -notlike '*--watcher*') "
        "}; foreach ($p in $targets) { Stop-Process -Id $p.ProcessId -Force }"
    )
    run_powershell(command)


def run_watcher() -> None:
    while True:
        if is_desktop_codex_running():
            start_widget_process()
        else:
            stop_widget_processes()
        time.sleep(5)


def main() -> None:
    parser = argparse.ArgumentParser(description="Codex quota desktop widget")
    parser.add_argument("--once", action="store_true", help="print the latest quota snapshot and exit")
    parser.add_argument("--watcher", action="store_true", help="follow Codex Desktop and start/stop the widget")
    parser.add_argument("--widget", action="store_true", help="run the widget window")
    args = parser.parse_args()

    if args.watcher:
        run_watcher()
        return

    if args.once:
        snapshot = read_quota_snapshot()
        if snapshot is None:
            print(json.dumps({"ok": False, "error": "no rate_limits found"}, ensure_ascii=False))
            return
        print(json.dumps({
            "ok": True,
            "primary_remaining": snapshot.primary.remaining,
            "secondary_remaining": snapshot.secondary.remaining,
            "primary_resets": fmt_datetime(snapshot.primary.resets_at),
            "secondary_resets": fmt_datetime(snapshot.secondary.resets_at),
            "reset_credits": snapshot.reset_credits,
            "reset_credit_expires": [fmt_datetime(item) for item in snapshot.reset_credit_expires_at or []],
            "stale": snapshot.stale,
            "message": snapshot.message,
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
