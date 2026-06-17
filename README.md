# Codex Quota Widget

粉白配色的 Windows 桌面小窗，用来显示 Codex 本地日志里的最近一次额度快照。

## 功能

- 显示五小时额度、周额度和对应刷新时间。
- 每 30 秒重新读取一次 Codex 本地日志。
- 右键菜单支持重新读取、复制摘要、切换置顶和退出。
- 可拖动位置，位置保存到 `D:\Codex\quota_widget\settings.json`。
- 可安装 watcher：Codex Desktop 打开时自动启动小窗，Codex Desktop 关闭时自动关闭小窗。

## 使用

直接启动小窗：

```powershell
powershell -ExecutionPolicy Bypass -File .\run_quota_widget.ps1
```

安装自动跟随 Codex 开关：

```powershell
powershell -ExecutionPolicy Bypass -File .\install_quota_autostart.ps1
```

卸载自动启动：

```powershell
powershell -ExecutionPolicy Bypass -File .\uninstall_quota_autostart.ps1
```

## 说明

这个小窗读取的是 Codex 本地会话日志中的 `rate_limits` 快照，不会主动请求官方服务器，也不会保存账号密码。
