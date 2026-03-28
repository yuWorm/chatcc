# ChatCC

通过即时通讯（IM）控制 Claude Code 的编排系统。在 Telegram、飞书、微信或本地终端中与 AI 对话，远程管理编码项目。

## 架构

```
IM Channel ──▶ Router ──▶ Dispatcher Agent ──▶ Claude Code Session
(Telegram/      (命令识别      (pydantic-ai,        (claude-agent-sdk,
 飞书/微信/       拦截/增强/      工具调度,              项目任务执行,
 CLI)           透传)          上下文构建)             审批与回调)
```

**核心模块：**

| 模块 | 职责 |
|------|------|
| `channel/` | 可插拔 IM 后端（CLI、Telegram、飞书、微信 iLink） |
| `command/` | 命令注册与规格定义（`CommandSpec`、`RouteType`） |
| `router/` | 用户消息分类：拦截命令 / 增强命令 / 透传 |
| `agent/` | Dispatcher 代理 — 注册工具、构建系统提示词、多 Provider 支持 |
| `claude/` | Claude Code 会话管理、任务队列、事件钩子 |
| `project/` | 项目 CRUD、YAML 持久化、会话日志与任务日志 |
| `memory/` | 对话历史（JSONL）、长期记忆（`MEMORY.md`）、摘要压缩 |
| `approval/` | 危险操作风险评估与人工审批队列 |
| `cost/` | 预算控制与花费追踪（Agent + Claude Code 双维度） |
| `service/` | 后台进程管理（启动/停止/监控） |
| `tools/` | Agent 工具集 — 项目、命令、服务、会话、技能安装 |
| `setup/` | 交互式配置向导（渠道 + AI Provider） |
| `personas/` | 可定制的系统人设模板 |

## 安装

**环境要求：** Python >= 3.12, [uv](https://docs.astral.sh/uv/)

### 使用 uv 从 GitHub 安装

```bash
# 直接安装（推荐）
uv tool install git+https://github.com/yuWorm/chatcc.git

# 或者安装到当前项目
uv add git+https://github.com/yuWorm/chatcc.git

# 安装指定分支
uv tool install git+https://github.com/yuWorm/chatcc.git@main

# 安装指定 commit 或 tag
uv tool install git+https://github.com/yuWorm/chatcc.git@<commit-or-tag>
```

### 从源码安装（开发用）

```bash
git clone https://github.com/yuWorm/chatcc.git
cd chatcc
uv sync
```

## 快速开始

```bash
# 交互式初始化（选择 AI Provider + IM 渠道）
chatcc init

# 启动
chatcc run
```

## CLI 命令

| 命令 | 说明 |
|------|------|
| `chatcc init` | 交互式配置向导（AI Provider、IM 渠道） |
| `chatcc init --reset` | 重置并重新初始化全部配置 |
| `chatcc auth --channel <type>` | 单独配置某个渠道的认证凭据 |
| `chatcc run` | 启动服务 |
| `chatcc run --channel <type>` | 指定 IM 渠道启动（覆盖配置文件） |
| `chatcc run --config <path>` | 指定配置文件路径 |
| `chatcc run --debug` | 调试模式启动 |

## 配置

配置文件位于 `~/.chatcc/config.yaml`，支持 `${ENV_VAR}` 环境变量替换。可通过环境变量 `CHATCC_HOME` 自定义配置目录（默认 `~/.chatcc`）。

**数据目录：** `~/.chatcc/`（包含 `projects/`、`history/`、`memory/`、`services/`）

### 完整配置示例

```yaml
# 数据存储目录（默认 ~/.chatcc）
data_dir: ~/.chatcc

# 工作区根目录（默认 ~）
workspace: ~/projects

# ── IM 渠道 ──────────────────────────────────────────
channel:
  type: telegram                # cli / telegram / feishu / wechat
  telegram:
    bot_token: ${TELEGRAM_BOT_TOKEN}
    # ... 其他 Telegram 配置
  feishu:
    app_id: ${FEISHU_APP_ID}
    app_secret: ${FEISHU_APP_SECRET}
    # ... 其他飞书配置
  wechat:
    # ... 微信 iLink 配置

# ── AI Provider ──────────────────────────────────────
agent:
  active_provider: anthropic    # 当前使用的 Provider 名称
  persona: default              # 系统人设模板名称
  memory:
    summarize_threshold: 50     # 对话条数达到此值时触发摘要压缩
    keep_recent: 10             # 压缩后保留最近的消息条数
    recent_daily_notes: 3       # 长期记忆中保留最近几天的笔记
  providers:
    anthropic:
      name: anthropic
      model: claude-sonnet-4-20250514
      api_key: ${ANTHROPIC_API_KEY}
    openai:
      name: openai
      model: gpt-4o
      api_key: ${OPENAI_API_KEY}
      type: chat                # chat（Chat Completions）或 responses（Responses API）
    google:
      name: google
      model: gemini-2.5-pro
      api_key: ${GOOGLE_API_KEY}
    custom:
      name: my-llm
      model: my-model
      api_key: ${CUSTOM_API_KEY}
      base_url: https://api.example.com/v1   # 自定义 OpenAI 兼容 API 地址

# ── 安全策略 ─────────────────────────────────────────
security:
  dangerous_tool_patterns:      # 触发人工审批的危险命令正则
    Bash:
      - '\brm\s'
      - '\bsudo\b'
      - '\bcurl\b.*\|\s*bash'
    Write:
      - '/etc/'
      - '/system/'

# ── Claude Code 会话默认值 ───────────────────────────
claude_defaults:
  permission_mode: acceptEdits  # Claude Code 权限模式
  setting_sources:              # 配置来源优先级
    - project
  model: null                   # 覆盖 Claude Code 使用的模型（null 使用默认）

# ── 预算控制 ─────────────────────────────────────────
budget:
  daily_limit: 10.0             # 每日花费上限（美元），null 为不限制

# ── 会话生命周期 ─────────────────────────────────────
session_policy:
  max_tasks_per_session: 10     # 单会话最大任务数，超过后轮转新会话
  max_cost_per_session: 2.0     # 单会话最大花费（美元），超过后轮转
  idle_disconnect_seconds: 300  # 会话空闲超时（秒），超时后断开
  restore_on_startup: true      # 启动时是否恢复上次未完成的会话
  compress_on_rotate: false     # 会话轮转时是否压缩历史摘要

# ── 富文本消息 ───────────────────────────────────────
rich_message:
  parse_agent_markdown: false   # 是否解析 Agent 回复中的 Markdown 为富文本
```

### 配置项说明

#### `channel` — IM 渠道

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `type` | string | `cli` | 渠道类型：`cli` / `telegram` / `feishu` / `wechat` |
| `telegram` | object | `{}` | Telegram Bot 配置（通过 `chatcc auth` 生成） |
| `feishu` | object | `{}` | 飞书应用配置 |
| `wechat` | object | `{}` | 微信 iLink 配置 |

#### `agent` — AI Provider 与对话

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `active_provider` | string | `anthropic` | 当前激活的 Provider 名称（对应 `providers` 中的 key） |
| `persona` | string | `default` | 系统人设模板，对应 `~/.chatcc/personas/` 下的文件 |
| `memory.summarize_threshold` | int | `50` | 对话消息数达到此值时自动压缩 |
| `memory.keep_recent` | int | `10` | 压缩后保留的最近消息条数 |
| `memory.recent_daily_notes` | int | `3` | 长期记忆中保留最近几天的日记 |

每个 Provider 支持的字段：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | string | `""` | Provider 标识 |
| `model` | string | `""` | 模型名称 |
| `api_key` | string | `""` | API 密钥，建议使用 `${ENV_VAR}` |
| `base_url` | string | `null` | 自定义 API 地址（OpenAI 兼容接口） |
| `type` | string | `chat` | OpenAI 协议类型：`chat`（Chat Completions）或 `responses`（Responses API） |

#### `security` — 安全策略

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `dangerous_tool_patterns` | object | 见下方 | 按工具名分组的危险命令正则，匹配时触发人工审批 |

默认规则：`Bash` 工具拦截 `rm`、`sudo`、`curl | bash`；`Write` 工具拦截写入 `/etc/`、`/system/`。

#### `claude_defaults` — Claude Code 会话默认值

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `permission_mode` | string | `acceptEdits` | Claude Code 权限模式 |
| `setting_sources` | list | `["project"]` | 配置来源列表 |
| `model` | string | `null` | 覆盖 Claude Code 模型，`null` 使用默认 |

#### `budget` — 预算控制

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `daily_limit` | float | `null` | 每日花费上限（美元），`null` 不限制 |

#### `session_policy` — 会话生命周期

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `max_tasks_per_session` | int | `10` | 单会话最大任务数 |
| `max_cost_per_session` | float | `2.0` | 单会话最大花费（美元） |
| `idle_disconnect_seconds` | int | `300` | 空闲超时断开（秒） |
| `restore_on_startup` | bool | `true` | 启动时恢复上次会话 |
| `compress_on_rotate` | bool | `false` | 轮转时压缩历史摘要 |

#### `rich_message` — 富文本消息

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `parse_agent_markdown` | bool | `false` | 解析 Agent Markdown 为渠道富文本格式 |

## IM 渠道支持

| 渠道 | 状态 | 说明 |
|------|------|------|
| CLI | ✅ | 本地终端调试 |
| Telegram | ✅ | python-telegram-bot |
| 飞书 | ✅ | Lark OpenAPI |
| 微信 | ✅ | iLink 协议 + AES 加密 |

## 依赖

- **AI 框架：** pydantic-ai、claude-agent-sdk
- **IM 集成：** python-telegram-bot、lark-oapi、aiohttp
- **工具链：** click、questionary、loguru、pyyaml、cryptography、qrcode

## 开发

```bash
git clone https://github.com/yuWorm/chatcc.git
cd chatcc
uv sync --extra dev
pytest
```

## License

MIT
