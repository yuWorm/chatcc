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
| `chatcc run --config <path>` | 指定配置文件路径 |
| `chatcc run --debug` | 调试模式启动 |

## 配置

配置文件位于 `~/.chatcc/config.yaml`，支持 `${ENV_VAR}` 环境变量替换。

```yaml
channel:
  type: telegram          # cli / telegram / feishu / wechat

agent:
  active_provider: anthropic
  providers:
    anthropic:
      name: anthropic
      model: claude-sonnet-4-20250514
      api_key: ${ANTHROPIC_API_KEY}

security:
  workspace_root: ~/projects

budget:
  daily_limit: 10.0
  session_limit: 5.0
```

**数据目录：** `~/.chatcc/`（包含 `projects/`、`history/`、`memory/`、`services/`）

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
