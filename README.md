# ChatCC

通过即时通讯（IM）控制 Claude Code 的编排系统。在 Telegram、飞书、微信或本地终端中与 AI 对话，远程管理编码项目。

## 架构

```
IM Channel ──▶ Router ──▶ Dispatcher Agent ──▶ Claude Code Session
(Telegram/      (slash       (pydantic-ai,        (claude-agent-sdk,
 飞书/微信/       命令路由)      工具调度)              项目任务执行)
 CLI)
```

**核心模块：**

| 模块 | 职责 |
|------|------|
| `channel/` | 可插拔 IM 后端（CLI、Telegram、飞书、微信） |
| `router/` | 斜杠命令识别与路由（拦截 / 增强 / 透传） |
| `agent/` | Dispatcher 代理，注册工具并构建上下文指令 |
| `claude/` | Claude Code 会话管理、任务执行与事件通知 |
| `project/` | 项目 CRUD，YAML 持久化，路径安全校验 |
| `memory/` | 对话历史、长期记忆、摘要管理 |
| `approval/` | 危险操作审批 |
| `cost/` | 预算控制与花费追踪 |
| `tools/` | Agent 可调用的工具集（项目/命令/服务/会话等） |

## 快速开始

**环境要求：** Python >= 3.12

```bash
# 安装
pip install -e .

# 交互式初始化（选择 AI 提供商 + IM 渠道）
chatcc init

# 启动
chatcc run
```

## CLI 命令

| 命令 | 说明 |
|------|------|
| `chatcc init` | 交互式配置向导（AI 提供商、IM 渠道） |
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

## 依赖

- **AI 框架：** pydantic-ai、claude-agent-sdk
- **IM 集成：** python-telegram-bot、lark-oapi、aiohttp
- **工具链：** click、questionary、loguru、pyyaml、cryptography、qrcode

## 开发

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT
