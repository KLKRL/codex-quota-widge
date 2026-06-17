# Codex 额度桌面小窗计划

## 目标

做一个放在桌面角落的轻量小窗口，用来显示 Codex 当前额度状态，降低频繁打开设置页面查看额度的麻烦。

它应该做到：

- 不挡输入框，不嵌在 Codex 对话界面里。
- 视觉上克制、干净、像一个桌面状态组件。
- 自动读取 Codex 本地日志中的最近一次额度信息。
- 显示主额度、周额度、刷新时间和数据更新时间。
- 可以拖动位置、置顶、手动刷新、退出。
- 不安装新依赖，不往 C 盘放大型文件。

## 数据来源判断

Codex 本地会话日志中存在 `rate_limits` 字段，例如：

- `primary.used_percent`：短窗口额度已用百分比。
- `primary.resets_at`：短窗口刷新时间，Unix 时间戳。
- `secondary.used_percent`：周额度已用百分比。
- `secondary.resets_at`：周额度刷新时间，Unix 时间戳。
- `plan_type`：账号计划类型。

因此第一版采用“只读本地日志”的方式，不需要登录网页、不需要抓包、不需要保存账号密码。

局限：

- 日志只有在 Codex 产生新消息或额度事件后才会更新。
- 如果官方以后改字段名，程序需要同步调整解析逻辑。
- 这个小窗显示的是 Codex 最近一次写入日志的额度快照，不是实时向服务器请求的官方接口。

## 设计方案

### 形态

使用 Python 标准库 `tkinter` 做原生桌面浮窗：

- 无边框窗口。
- 默认置顶。
- 可拖动。
- 右键菜单。
- 体积约 `320 x 188`，适合放在屏幕右上角或侧边。

### 视觉

采用深色磨砂感卡片：

- 背景：接近黑灰。
- 主文字：柔和白色。
- 次级文字：灰蓝色。
- 进度条：额度充足为绿色，偏紧张为黄色，危险为红色。
- 圆角、细边框、轻微分区，避免官方悬浮提示那种生硬感。

### 交互

右键菜单：

- 立即刷新。
- 复制当前额度摘要。
- 切换置顶。
- 退出。

拖动：

- 鼠标左键按住窗口任意位置拖动。
- 松开后保存位置，下次启动恢复。

### 文件布局

- `outputs/codex_quota_plan.md`：本计划。
- `outputs/codex_quota_widget.py`：桌面小窗程序。
- `outputs/run_quota_widget.ps1`：一键启动脚本。
- `D:\Codex\quota_widget\settings.json`：小窗运行时设置。

## 实施步骤

1. 确认本机 Python 和 Tkinter 可用。
2. 从 `C:\Users\lenovo\.codex\sessions` 和 `C:\Users\lenovo\.codex\archived_sessions` 中读取最近的 `rate_limits`。
3. 将 `used_percent` 转换为“剩余额度百分比”。
4. 把 Unix 刷新时间转换为本地时间。
5. 实现小窗 UI、进度条、颜色状态、右键菜单和拖动保存。
6. 增加命令行 `--once`，用于不打开窗口时验证解析结果。
7. 启动小窗，确认能运行成功。

## 后续可升级

- 打包成 `.exe`，放到开机启动。
- 加入更小的“迷你模式”。
- 增加低于 20% 时的温和提醒。
- 如果以后找到官方稳定 API，可以把数据源从日志快照升级为实时查询。

## GitHub 调研补充

已经搜到的相关项目和结论：

- OpenAI 官方 Codex 仓库里有人提出过“桌面额度小组件”需求，说明这个痛点不是个例，但官方还没有给出成熟独立窗口方案。
- `CodeZeno/Claude-Code-Usage-Monitor` 是 Windows 任务栏小组件，支持可选 Codex 显示，体验方向接近，但它主要是任务栏工具，不是桌面浮窗。
- `jpajak/ai-gauge` 是跨平台 Qt 小组件，支持 Windows/Linux 浮窗和 macOS 菜单栏，但需要 PyQt6 等额外依赖。
- `steipete/CodexBar`、`AgentLimits`、`AIQuotaBar` 等主要面向 macOS 菜单栏/WidgetKit，不适合直接拿来改 Windows 桌面小窗。
- `psinghmanager/g4-Claw-counter` 也是 Windows + tkinter + 标准库路线，技术选择和本方案一致，但它更偏 token/cost 统计，不是专门显示 Codex 官方额度窗口。

当前判断：

第一版继续采用“Python 标准库 + 本地日志”的方案更适合这台 Windows 机器。它不需要安装依赖，不需要拉大型仓库，不引入账号 cookie/API key 风险，也更容易按你的审美快速调整。后续如果想做任务栏托盘或打包 exe，可以再借鉴 `CodeZeno/Claude-Code-Usage-Monitor` 或 `ai-gauge` 的交互形态。
