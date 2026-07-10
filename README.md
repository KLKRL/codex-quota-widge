# Codex Quota Widget

粉白配色的 Windows 桌面小窗，用来显示 Codex 当前账号的剩余额度。

![Theme preview](theme_preview.png)

## 功能

- 显示五小时额度、周额度和对应刷新时间。
- 每 30 秒优先通过 ChatGPT/Codex 官方 `wham/usage` 接口重新读取一次额度。
- 显示可用的 rate-limit reset credits 数量；复制摘要时也会带上重置次数。
- 右键菜单支持重新读取、切换配色、切换大小、复制摘要、切换置顶和退出。
- 可拖动位置，位置保存到 `D:\Codex\quota_widget\settings.json`。
- 可安装 watcher：Codex Desktop 打开时自动启动小窗，Codex Desktop 关闭时自动关闭小窗。
- 右键菜单可切换内置配色：莓果白、奶油粉、樱花、薄荷、天空、夜粉。

## 使用

### 普通用户

下载 `CodexQuotaWidget.exe` 后双击运行即可。

安装“跟随 Codex 自动开关”：

```powershell
powershell -ExecutionPolicy Bypass -File .\install_quota_autostart.ps1
```

安装后：

- 打开 Codex Desktop 时，小窗会自动打开。
- 关闭 Codex Desktop 时，小窗会自动关闭。
- Windows 登录后会自动启动 watcher，但只有 Codex Desktop 运行时才显示小窗。

卸载自动启动：

```powershell
powershell -ExecutionPolicy Bypass -File .\uninstall_quota_autostart.ps1
```

### 开发者

直接用 Python 启动小窗：

```powershell
powershell -ExecutionPolicy Bypass -File .\run_quota_widget.ps1
```

## 说明

这个小窗优先读取本机 `~/.codex/auth.json` 里的 Codex 登录凭证，并请求 ChatGPT/Codex 官方的 `wham/usage` 和 `wham/rate-limit-reset-credits` 接口；读取失败时，会依次回落到本机 Codex CLI 的 `app-server --stdio` / `account/rateLimits/read`，以及 Codex 本地会话日志里的 `rate_limits` 快照。

右键菜单里的“重新读取”会立即强制重新请求官方接口。程序不会保存账号密码、token、cookie 或完整账号 ID。

## 配色

内置配色：

- 莓果白：默认主题，粉白顶栏，适合长期放桌面。
- 奶油粉：更柔和，偏暖。
- 樱花：更轻、更白。
- 薄荷：绿色低焦虑配色。
- 天空：蓝白清爽配色。
- 夜粉：深色桌面更协调。

右键小窗，点击 `配色: ...` 即可循环切换，选择会自动保存。

## 大小

右键小窗，点击 `大小: ...` 可在 85%、100%、115%、130% 四档之间循环切换，选择会自动保存。

## 打包

开发者可以用 PyInstaller 打包：

```powershell
pyinstaller --noconsole --onefile --name CodexQuotaWidget codex_quota_widget.py
```
