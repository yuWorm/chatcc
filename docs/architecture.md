# ChatCC 架构设计文档

> 通过 IM 软件远程控制 Claude Code 进行项目开发的调度系统

---

## 一、系统总览

### 1.1 定位

ChatCC 是一个 **调度中枢**，而非又一个 AI 编程助手。它的职责边界:


| 主 Agent 负责 | Claude Code 负责         |
| ---------- | ---------------------- |
| 理解用户意图     | 一切代码相关的思考和执行           |
| 管理项目/会话状态  | 代码编写、调试、重构             |
| 格式化反馈到 IM  | 文件操作、命令执行              |
| 安全审批决策     | 资料查询、文档理解              |
| 记忆管理（自身）   | 自身 session 历史和 compact |


主 Agent **绝不试图理解代码**，只做调度和状态管理。

### 1.2 技术栈


| 组件             | 选型                        | 说明                     |
| -------------- | ------------------------- | ---------------------- |
| 语言             | Python 3.12+              |                        |
| 包管理            | uv                        | `uv venv` 创建本地虚拟环境     |
| 主 Agent 框架     | pydantic-ai               | 用轻量模型做调度               |
| Claude Code 交互 | claude-agent-sdk (Python) | `ClaudeSDKClient` 管理会话 |
| 配置             | YAML / TOML               | 全局 + 项目级配置             |
| 持久化            | 文件系统 (JSONL + Markdown)   | 无外部数据库依赖               |


### 1.3 架构全景

```
┌─────────────────────────────────────────────────────────────────────┐
│                          IM 渠道层                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐            │
│  │ Telegram │  │ Discord  │  │   CLI    │  │  其他... │            │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘            │
│       └──────────────┴─────────────┴─────────────┘                  │
│                          │                                           │
│                  MessageChannel (统一接口)                            │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ InboundMessage / OutboundMessage
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│                       MessageRouter                                  │
│                                                                      │
│  ┌─ 快捷命令拦截 (不走 LLM) ──────────────────────────────────────┐  │
│  │  /y /n /pending  → ApprovalTable                               │  │
│  │  /project list   → ProjectManager (直接响应)                    │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                           │                                          │
│                  其他消息 → 主 Agent                                  │
└──────────────────────────┬───────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│                     主 Agent (pydantic-ai)                           │
│                                                                      │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐            │
│  │ 记忆管理器   │  │ 工具集      │  │ 系统提示词 + 人设 │            │
│  │             │  │             │  │                  │            │
│  │ • 会话历史  │  │ • 项目管理  │  └──────────────────┘            │
│  │ • 会话摘要  │  │ • 消息发送  │                                   │
│  │ • 长期记忆  │  │ • 命令执行  │                                   │
│  └─────────────┘  │ • 服务启动  │                                   │
│                   │ • Claude会话│                                   │
│                   │ • 工具安装  │                                   │
│                   └──────┬──────┘                                   │
└──────────────────────────┬───────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│                  Claude Code 会话管理器                                │
│                                                                      │
│  ┌─ 项目 A ──────────────────┐  ┌─ 项目 B ──────────────────┐      │
│  │ ClaudeSDKClient (active)  │  │ ClaudeSDKClient (active)  │      │
│  │ session-3 ← 活跃          │  │ session-1 ← 活跃          │      │
│  │ session-2 ← 归档          │  └────────────────────────────┘      │
│  │ session-1 ← 归档          │                                      │
│  └────────────────────────────┘                                      │
│                                                                      │
│  ┌─ Hook 系统 ───────────────────────────────────────────────┐      │
│  │ Notification → 转发 IM                                    │      │
│  │ PreToolUse   → 安全检查 → ApprovalTable (危险操作)        │      │
│  │ PostToolUse  → 状态更新                                   │      │
│  │ TaskNotification → 任务完成/失败通知                       │      │
│  └───────────────────────────────────────────────────────────┘      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 二、消息渠道层

### 2.1 统一接口

所有 IM 渠道实现同一个抽象接口。主系统只和接口交互，不感知底层渠道实现。

```python
@dataclass
class InboundMessage:
    sender_id: str
    content: str
    chat_id: str
    media: list[str] | None = None
    raw: Any = None  # 渠道原始消息对象


@dataclass
class OutboundMessage:
    chat_id: str
    content: str | RichMessage    # 简单场景传 str，复杂场景传 RichMessage
    reply_to: str | None = None


class MessageChannel(ABC):

    @abstractmethod
    async def start(self) -> None:
        """启动渠道连接"""

    @abstractmethod
    async def stop(self) -> None:
        """断开连接，清理资源"""

    @abstractmethod
    async def send(self, message: OutboundMessage) -> None:
        """发送消息到渠道 (内部调用 render 处理 RichMessage)"""

    @abstractmethod
    def render(self, message: RichMessage) -> Any:
        """将 RichMessage 转为渠道原生消息格式"""

    @abstractmethod
    def on_message(self, callback: Callable[[InboundMessage], Awaitable[None]]) -> None:
        """注册消息回调"""

    def register_auth_commands(self, cli: CliGroup) -> None:
        """注册渠道认证相关的 CLI 子命令 (可选实现, 默认无操作)"""
        pass

    @abstractmethod
    def is_authenticated(self) -> bool:
        """检查渠道是否已完成认证"""
```

### 2.2 认证机制

部分渠道不支持直接填写 token（如需要 OAuth 流程、扫码登录等），需要交互式认证。认证逻辑完全由渠道实现，主系统通过 CLI 扩展命令统一入口:

```bash
# 统一入口
chatcc auth            # 对当前配置的渠道执行认证
chatcc auth --channel telegram   # 指定渠道认证

# 各渠道自行实现的认证流程示例:
# Telegram: 提示输入 bot token → 验证 → 写入配置
# WeChat:   启动本地 HTTP 回调 → 展示二维码 → 扫码完成
# Discord:  打开 OAuth 授权页 → 回调获取 token → 写入配置
```

实现方式: 每个渠道通过 `register_auth_commands()` 向 CLI 注册自己的认证子命令和流程:

```python
class WeChatChannel(MessageChannel):

    def register_auth_commands(self, cli: CliGroup) -> None:
        @cli.command("auth")
        def auth():
            """WeChat 扫码登录"""
            qr = self._generate_qr_code()
            print(f"请扫描二维码登录:\n{qr}")
            token = self._wait_for_scan()
            self._save_credentials(token)
            print("认证成功")

    def is_authenticated(self) -> bool:
        return self._load_credentials() is not None


class TelegramChannel(MessageChannel):

    def register_auth_commands(self, cli: CliGroup) -> None:
        @cli.command("auth")
        def auth(token: str | None = None):
            """设置 Telegram Bot Token"""
            if not token:
                token = input("请输入 Bot Token: ")
            if self._verify_token(token):
                self._save_credentials(token)
                print("认证成功")
            else:
                print("Token 无效")

    def is_authenticated(self) -> bool:
        return self.config.get("token") is not None
```

启动时检查认证状态:

```python
async def startup(channel: MessageChannel):
    if not channel.is_authenticated():
        print(f"渠道未认证，请先运行: chatcc auth")
        sys.exit(1)
    await channel.start()
```

### 2.3 设计约束

- **同时只启动一种渠道**，防止多平台消息冲突
- 渠道启动类型在全局配置中指定
- 长消息拆分由各渠道实现内部处理（Telegram 4096 / Discord 2000），主系统不关心
- 渠道启动前检查 `is_authenticated()`，未认证则提示用户执行 `chatcc auth`

### 2.3 RichMessage 消息格式

不同渠道能力差异很大（Telegram 支持按钮、Markdown；WeChat 仅纯文本）。主系统输出**语义化的富消息**，各渠道实现自行降级渲染。

#### 渠道能力对比


| 能力       | Telegram       | Discord | WeChat | CLI |
| -------- | -------------- | ------- | ------ | --- |
| Markdown | 部分支持           | 支持      | 不支持    | 支持  |
| 按钮/快捷操作  | InlineKeyboard | Button  | 不支持    | 不支持 |
| 代码块      | 支持             | 支持      | 不支持    | 支持  |
| 消息长度     | 4096           | 2000    | ~2000  | 无限  |
| 引用回复     | 支持             | 支持      | 支持     | 不支持 |


#### 消息元素定义

```python
@dataclass
class TextElement:
    """纯文本"""
    content: str

@dataclass
class CodeElement:
    """代码块"""
    code: str
    language: str = ""

@dataclass
class ActionButton:
    """可操作按钮 (渠道不支持时降级为文本命令提示)"""
    label: str       # 显示文本: "确认"
    command: str      # 对应命令: "/y 3"

@dataclass
class ActionGroup:
    """一组操作按钮"""
    buttons: list[ActionButton]

@dataclass
class ProgressElement:
    """进度指示"""
    description: str
    project: str

@dataclass
class DividerElement:
    """分隔线"""
    pass

MessageElement = TextElement | CodeElement | ActionGroup | ProgressElement | DividerElement

@dataclass
class RichMessage:
    """语义化的富消息，渠道无关"""
    elements: list[MessageElement]
    reply_to: str | None = None
    project_tag: str | None = None   # 来源项目标记
```

#### 设计原则

1. **元素集保持最小化**: 只定义项目实际需要的几种元素，后续按需扩展
2. **降级是渠道的责任**: 主系统永远输出完整 `RichMessage`，各渠道的 `render()` 自行决定如何降级
3. `**send` 内部调 `render`**: 渠道的 `send()` 方法判断 content 类型，`RichMessage` 走 `render()`，`str` 直接发送

#### 示例: 权限确认消息

主系统发出:

```python
RichMessage(
    project_tag="myapp",
    elements=[
        TextElement("Claude Code 请求执行危险操作:"),
        CodeElement("rm -rf dist/", language="bash"),
        TextElement("工具: Bash | 请求 ID: #3"),
        ActionGroup(buttons=[
            ActionButton(label="允许", command="/y 3"),
            ActionButton(label="拒绝", command="/n 3"),
        ]),
    ]
)
```

**Telegram 渲染** (按钮能力):

```
[myapp] Claude Code 请求执行危险操作:

`rm -rf dist/`

工具: Bash | 请求 ID: #3

[ ✅ 允许 ]  [ ❌ 拒绝 ]     ← InlineKeyboard 按钮，点击自动发送命令
```

**WeChat 渲染** (无按钮，降级为文本命令):

```
[myapp] Claude Code 请求执行危险操作:

  rm -rf dist/

工具: Bash | 请求 ID: #3
回复 /y 3 允许，/n 3 拒绝
```

**CLI 渲染** (纯文本):

```
[myapp] Claude Code 请求执行危险操作:
  $ rm -rf dist/
  工具: Bash | 请求 ID: #3
  → /y 3 允许 | /n 3 拒绝
```

#### 渠道渲染器示例

```python
class TelegramChannel(MessageChannel):

    def render(self, message: RichMessage) -> tuple[str, InlineKeyboardMarkup | None]:
        text_parts = []
        keyboard_buttons = []

        if message.project_tag:
            text_parts.append(f"[{message.project_tag}]")

        for element in message.elements:
            match element:
                case TextElement(content=content):
                    text_parts.append(content)
                case CodeElement(code=code, language=lang):
                    text_parts.append(f"```{lang}\n{code}\n```")
                case ActionGroup(buttons=buttons):
                    row = [
                        InlineKeyboardButton(b.label, callback_data=b.command)
                        for b in buttons
                    ]
                    keyboard_buttons.append(row)
                case ProgressElement(description=desc):
                    text_parts.append(f"⏳ {desc}")
                case DividerElement():
                    text_parts.append("───────────")

        text = "\n\n".join(text_parts)
        keyboard = InlineKeyboardMarkup(keyboard_buttons) if keyboard_buttons else None
        return text, keyboard

    async def send(self, message: OutboundMessage) -> None:
        if isinstance(message.content, RichMessage):
            text, keyboard = self.render(message.content)
            for chunk in self._split(text, 4096):
                await self._bot.send_message(
                    message.chat_id, chunk,
                    reply_markup=keyboard, parse_mode="MarkdownV2",
                )
        else:
            for chunk in self._split(str(message.content), 4096):
                await self._bot.send_message(message.chat_id, chunk)


class WeChatChannel(MessageChannel):

    def render(self, message: RichMessage) -> str:
        text_parts = []

        if message.project_tag:
            text_parts.append(f"[{message.project_tag}]")

        for element in message.elements:
            match element:
                case TextElement(content=content):
                    text_parts.append(content)
                case CodeElement(code=code):
                    indented = "\n".join(f"  {line}" for line in code.splitlines())
                    text_parts.append(indented)
                case ActionGroup(buttons=buttons):
                    hints = "，".join(f"{b.command} {b.label}" for b in buttons)
                    text_parts.append(f"回复 {hints}")
                case ProgressElement(description=desc):
                    text_parts.append(f"[进行中] {desc}")
                case DividerElement():
                    text_parts.append("----------")

        return "\n".join(text_parts)
```

---

## 三、消息路由

### 3.1 MessageRouter

所有入站消息的第一个处理节点。在消息进入主 Agent 之前，拦截快捷命令直接处理:

```
InboundMessage
    │
    ▼
MessageRouter.route()
    │
    ├── /y, /n, /pending       → ApprovalTable (权限确认)
    ├── /stop                  → 中断当前 Claude Code 任务
    ├── /status                → 查询当前任务状态
    │
    └── 其他所有消息           → 主 Agent (LLM 处理)
```

### 3.2 快捷命令不走 LLM

权限确认、状态查询等操作是确定性的，在路由层直接处理，节省 LLM 调用:

```python
class MessageRouter:
    INTERCEPT_COMMANDS = {"/y", "/n", "/pending", "/stop", "/status"}

    async def route(self, message: InboundMessage):
        cmd = message.content.strip().split()[0].lower()
        if cmd in self.INTERCEPT_COMMANDS:
            return await self.handle_command(message)
        return await self.dispatch_to_agent(message)
```

---

## 四、主 Agent

### 4.1 Agent 定位

使用 pydantic-ai 框架做调度。支持多 AI 供应商及自定义供应商，通过配置文件切换。所有代码理解和开发能力交给 Claude Code。

```python
from pydantic_ai import Agent

model = build_model_from_config(config.agent.providers, config.agent.active_provider)

dispatcher = Agent(
    model,
    system_prompt=load_system_prompt(),   # 人设 + 规则
)
```

### 4.2 多供应商支持

主 Agent 支持配置多个 AI 供应商，通过 `active_provider` 字段切换当前使用的供应商。

#### 供应商配置模型

```python
@dataclass
class ProviderConfig:
    name: str                    # 供应商显示名称
    model: str                   # 模型标识
    api_key: str                 # API Key (支持环境变量引用)
    base_url: str | None = None  # 自定义 API 地址 (为空则使用官方默认)
```

#### 模型构建

pydantic-ai 原生支持 OpenAI 兼容协议，自定义供应商只需提供 `base_url`:

```python
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

def build_model_from_config(
    providers: dict[str, ProviderConfig],
    active: str,
) -> str | OpenAIModel:
    provider = providers[active]

    if provider.base_url:
        # 自定义供应商: 通过 OpenAI 兼容协议接入
        return OpenAIModel(
            provider.model,
            provider=OpenAIProvider(
                base_url=provider.base_url,
                api_key=provider.api_key,
            ),
        )

    # 官方供应商: 直接使用 pydantic-ai 标准格式 "provider:model"
    provider_prefix = {
        "anthropic": "anthropic",
        "openai": "openai",
        "google": "google-gla",
    }.get(active, active)

    return f"{provider_prefix}:{provider.model}"
```

#### 运行时切换

主 Agent 提供工具让用户通过 IM 指令切换供应商:

| 指令示例 | 行为 |
|---------|------|
| "切换到 openai" | 更新 `active_provider`，重建 Agent model |
| "用自建服务" | 切换到 `custom-llm` 配置 |
| "当前用的什么模型" | 返回当前供应商名称 + 模型 |

### 4.3 Agent Loop

主 Agent 不派生子 Agent，只做中央调度。消息处理采用**异步任务模型**:

```
┌──────────────────────────────────────────────────┐
│ 消息入口 (来自 MessageRouter)                      │
│                                                    │
│  ┌── 同步类消息 (查询/管理) ──→ 主 Agent 即时处理   │
│  │                                                 │
│  └── 异步类消息 (开发指令)   ──→ 任务管理器         │
│      ├── 定位目标项目 (指定/默认)                    │
│      ├── 主 Agent 理解意图，调用 Claude 会话工具     │
│      └── Claude Code 异步执行，回调通知结果          │
│                                                    │
│  同一项目内串行，跨项目可并行                        │
└──────────────────────────────────────────────────┘
```

### 4.3 系统提示词

分为静态部分（人设、规则）和动态部分（当前状态）:

```python
def build_system_prompt() -> str:
    static = load_persona()  # 人设提示词

    dynamic = "\n".join([
        f"当前时间: {datetime.now()}",
        f"当前默认项目: {project_manager.default_project.name}",
        f"活跃项目数: {project_manager.active_count}",
        f"待确认操作: {approval_table.pending_count}",
    ])

    memory_context = memory_manager.get_context()

    return f"{static}\n\n{dynamic}\n\n{memory_context}"
```

---

## 五、记忆系统

### 5.1 三层架构

主 Agent 自身的记忆分三层，与 Claude Code 的 session 历史**完全独立**。

```
┌──────────────────────────────────────────────────────────┐
│ 层级 1: 会话历史 + 摘要                                    │
│ 范围: 主 Agent 与用户的 IM 对话                             │
│ 生命周期: 随会话自动压缩                                    │
│ 存储: JSONL (append-only)                                  │
│ 触发压缩: 消息数 > 阈值 OR token 估算 > 阈值               │
├──────────────────────────────────────────────────────────┤
│ 层级 2: 工作记忆                                           │
│ 范围: 当前工作上下文                                        │
│ 内容: 各项目的任务状态、当前默认项目、近期操作摘要           │
│ 生命周期: 实时更新，注入每次 LLM 调用的 system prompt       │
├──────────────────────────────────────────────────────────┤
│ 层级 3: 长期记忆                                           │
│ 范围: 跨会话                                               │
│ 内容: 用户偏好、项目状态摘要、重要决策记录                   │
│ 存储: Markdown 文件 (memory/MEMORY.md + 每日笔记)          │
│ 管理: 主 Agent 通过工具读写，自行决定何时更新               │
└──────────────────────────────────────────────────────────┘
```

### 5.2 会话历史压缩

主 Agent 的 IM 对话历史需要自动压缩，防止 context window 溢出:

```
触发条件 (满足任一):
  1. 消息数 > SUMMARIZE_MESSAGE_THRESHOLD (默认 50)
  2. token 估算 > context_window * 75%

压缩流程:
  1. 保留最近 N 条消息 (如最近 10 条)
  2. 对旧消息用 LLM 生成摘要
  3. 从旧消息中提取重要事实 → 写入长期记忆
  4. 用 [会话摘要] 替换旧消息
```

### 5.3 长期记忆文件结构

```
~/.chatcc/memory/
├── MEMORY.md              # 核心长期记忆 (用户偏好、常用习惯)
└── 202603/
    ├── 20260325.md        # 每日笔记
    └── 20260326.md
```

注入方式: 构建 system prompt 时读取 `MEMORY.md` 和最近 3 天的每日笔记，拼入上下文。

### 5.4 与 Claude Code 记忆的关系

```
主 Agent 记忆                     Claude Code 记忆
    │                                  │
    │ 主 Agent 自行管理                │ SDK 自动管理
    │ (压缩、摘要、长期存储)            │ (session compact)
    │                                  │
    └──── 唯一交叉点 ─────────────────┘
          │
          当 Claude Code session 发生以下事件时,
          主 Agent 记录到自身上下文:
          • 任务完成: "项目A 完成了认证模块"
          • 会话切换: "项目A 切换到新会话"
          • 会话压缩: "项目A 会话自动压缩"
```

---

## 六、项目管理

### 6.1 项目模型

```python
@dataclass
class Project:
    name: str
    path: str                   # 项目绝对路径
    created_at: datetime
    is_default: bool = False
    config: ProjectConfig = field(default_factory=ProjectConfig)
```

### 6.2 默认项目机制

- 第一个创建的项目自动成为默认项目
- 未指定项目的指令全部路由到默认项目
- 通过主 Agent 指令切换默认项目（如 "切换到项目B"）
- 无项目时下达开发指令 → 提示用户先创建项目

### 6.3 项目操作


| 操作   | 触发方式       | 说明                |
| ---- | ---------- | ----------------- |
| 创建   | 主 Agent 工具 | 指定名称 + 路径，自动初始化配置 |
| 列出   | 主 Agent 工具 | 展示所有项目 + 各自状态     |
| 切换默认 | 主 Agent 工具 | 切换后续指令的默认目标       |
| 查看配置 | 主 Agent 工具 | 展示项目路径、关联会话、当前状态  |
| 删除   | 主 Agent 工具 | 归档项目配置，不删除项目文件    |


### 6.4 项目配置文件结构

```
~/.chatcc/
├── config.yaml                    # 全局配置
├── memory/                        # 主 Agent 记忆
│   ├── MEMORY.md
│   └── 202603/
│       └── 20260325.md
└── projects/
    ├── myapp/                     # 项目配置目录 (按项目名)
    │   ├── project.yaml           # 项目配置 (路径、默认选项)
    │   ├── sessions.yaml          # 会话列表 (session_id + 摘要)
    │   └── notes.md               # 项目笔记/上下文
    └── backend-api/
        ├── project.yaml
        ├── sessions.yaml
        └── notes.md
```

`project.yaml` 示例:

```yaml
name: myapp
path: /home/user/projects/myapp
created_at: "2026-03-25T10:00:00Z"
is_default: true
claude_options:
  permission_mode: acceptEdits
  setting_sources:
    - project
  model: null  # 使用默认模型
```

`sessions.yaml` 示例:

```yaml
active_session: "session-abc-123"
sessions:
  - id: "session-abc-123"
    summary: "实现用户认证模块"
    created_at: "2026-03-25T10:30:00Z"
    status: active
  - id: "session-xyz-789"
    summary: "初始化项目结构"
    created_at: "2026-03-24T14:00:00Z"
    status: archived
```

---

## 七、Claude Code 会话管理

### 7.1 每项目一个活跃 Client

每个项目维护一个 `ClaudeSDKClient` 实例，同时只有一个活跃 session:

```python
class ProjectSession:
    def __init__(self, project: Project):
        self.project = project
        self.client: ClaudeSDKClient | None = None
        self.active_session_id: str | None = None
        self.task_state: TaskState = TaskState.IDLE

    async def ensure_connected(self) -> ClaudeSDKClient:
        if not self.client:
            self.client = ClaudeSDKClient(options=self._build_options())
            await self.client.connect()
        return self.client

    def _build_options(self) -> ClaudeAgentOptions:
        return ClaudeAgentOptions(
            cwd=self.project.path,
            permission_mode="acceptEdits",
            setting_sources=["project"],   # 加载项目 CLAUDE.md
            can_use_tool=self._permission_handler,
            hooks={
                "Notification": [HookMatcher(hooks=[self._on_notification])],
                "PostToolUse": [HookMatcher(hooks=[self._on_tool_use])],
            },
            resume=self.active_session_id,  # 续接已有会话
        )
```

### 7.2 会话生命周期

```
         ┌──────────┐
         │ 无会话    │ ← 新项目初始状态
         └────┬─────┘
              │ 首次开发指令
              ▼
         ┌──────────┐
         │ 活跃会话  │ ← ClaudeSDKClient 连接中
         └──┬──┬────┘
            │  │
            │  └──→ 用户指令 "新开会话" / 达到阈值
            │              │
            │              ▼
            │       归档当前会话, 创建新 ClaudeSDKClient
            │
            └──→ 用户指令 "切回会话X"
                       │
                       ▼
                 resume=session_id 恢复旧会话
```

### 7.3 会话管理策略


| 操作     | 触发方式 | 实现                                     |
| ------ | ---- | -------------------------------------- |
| 继续当前会话 | 默认行为 | `client.query()` 续接                    |
| 手动新建会话 | 用户指令 | 归档旧 session，创建新 client                 |
| 恢复旧会话  | 用户指令 | `resume=session_id`                    |
| 列出会话   | 用户指令 | 读取 `sessions.yaml` + `list_sessions()` |


### 7.4 Hook 集成

通过 Claude Agent SDK 的 Hook 系统监听 Claude Code 的关键事件:


| Hook 事件        | 用途                      |
| -------------- | ----------------------- |
| `Notification` | 将 Claude Code 的通知转发到 IM |
| `PreToolUse`   | 安全检查，危险操作进入审批流程         |
| `PostToolUse`  | 更新任务状态                  |
| `PreCompact`   | 通知主 Agent "会话已压缩"       |
| `Stop`         | 任务自然结束时通知主 Agent        |


---

## 八、任务状态机

每个项目维护独立的任务状态:

```
         ┌──────┐
         │ IDLE │ ← 项目空闲
         └──┬───┘
            │ 主 Agent 下发开发指令
            ▼
      ┌──────────┐
      │ RUNNING  │ ← Claude Code 执行中
      └──┬──┬──┬─┘
         │  │  │
         │  │  └─→ 用户发新消息 (同项目, 非中断)
         │  │      → Steering: client.query(追加指令)
         │  │
         │  └────→ 用户发 /stop
         │         │
         │         ▼
         │   ┌──────────────┐
         │   │ INTERRUPTING │ ← client.interrupt() 已发送
         │   └──────┬───────┘
         │          │ receive_response() 消费完毕
         │          ▼
         │   ┌───────────┐
         │   │ CANCELLED  │ → 通知 IM → 回到 IDLE
         │   └───────────┘
         │
         │ Claude Code 执行完毕 (ResultMessage)
         ▼
   ┌───────────┐
   │ COMPLETED │ → 通知 IM → 回到 IDLE
   └───────────┘

   (异常情况)
   ┌──────────┐
   │ FAILED   │ → 通知 IM → 回到 IDLE
   └──────────┘
```

```python
class TaskState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    INTERRUPTING = "interrupting"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
```

---

## 九、安全审批系统

### 9.1 安全边界规则


| 规则                       | 实现方式                                    |
| ------------------------ | --------------------------------------- |
| 危险命令须用户同意                | `can_use_tool` 回调 → ApprovalTable       |
| 主 Agent 只在 workspace 中执行 | 路径校验: `realpath` 必须在 `WORKSPACE_ROOT` 内 |
| Claude Code 只在项目目录中      | `ClaudeAgentOptions(cwd=project.path)`  |


### 9.2 风险分级

```python
def assess_risk(tool_name: str, input_data: dict) -> Literal["safe", "dangerous", "forbidden"]:

    # 禁止: 超出项目目录的操作
    if is_path_escape(input_data):
        return "forbidden"

    # 安全: 只读操作
    SAFE_TOOLS = {"Read", "Grep", "Glob", "LS"}
    if tool_name in SAFE_TOOLS:
        return "safe"

    # 危险: 需要用户确认
    DANGEROUS_PATTERNS = {
        "Bash": [r"\brm\s", r"\bsudo\b", r"\bcurl\b.*\|\s*bash"],
        "Write": [r"/etc/", r"/system/"],
    }
    if tool_name in DANGEROUS_PATTERNS:
        for pattern in DANGEROUS_PATTERNS[tool_name]:
            if re.search(pattern, str(input_data)):
                return "dangerous"

    # 默认: 安全 (acceptEdits 模式下自动放行编辑操作)
    return "safe"
```

### 9.3 审批流程

危险操作通过 `ApprovalTable` 挂起等待用户确认。Claude Code CLI 不会断联，可安全长时间等待。

```
Claude Code 请求执行危险工具
    │
    ▼
can_use_tool 回调
    │
    ├── safe      → PermissionResultAllow (直接放行)
    ├── forbidden → PermissionResultDeny  (直接拒绝)
    └── dangerous → ApprovalTable.request_approval()
                        │
                        ├── 生成确认条目 (ID, 项目, 工具, 参数摘要)
                        ├── 发送确认消息到 IM
                        └── asyncio.Future 阻塞等待
                              │
                              用户回复 /y 或 /n
                              │
                              ▼
                        Future.set_result(True/False)
                              │
                              ▼
                        返回 Allow 或 Deny → Claude Code 继续
```

### 9.4 ApprovalTable

```python
@dataclass
class PendingApproval:
    id: int
    project: str
    tool_name: str
    input_summary: str
    future: asyncio.Future
    created_at: datetime
```

用户命令:


| 命令         | 行为             |
| ---------- | -------------- |
| `/y`       | 确认最早的一条待审批     |
| `/y 3`     | 确认 ID 为 3 的待审批 |
| `/y all`   | 全部确认           |
| `/n`       | 拒绝最早的一条        |
| `/n all`   | 全部拒绝           |
| `/pending` | 查看所有待确认列表      |


由于 Claude Code 串行请求权限，**同一项目同时最多 1 条待确认**。多条待确认仅出现在多项目并行场景。

---

## 十、主 Agent 工具集

### 10.1 工具分类

#### 项目管理类


| 工具                 | 功能              |
| ------------------ | --------------- |
| `create_project`   | 创建新项目 (名称 + 路径) |
| `list_projects`    | 列出所有项目及状态       |
| `switch_project`   | 切换默认项目          |
| `get_project_info` | 查看项目详情          |
| `delete_project`   | 归档项目配置          |


#### Claude Code 会话类


| 工具               | 功能                           |
| ---------------- | ---------------------------- |
| `send_to_claude` | 将开发指令发送到当前项目的 Claude Code 会话 |
| `list_sessions`  | 列出项目的所有会话                    |
| `switch_session` | 切换/恢复指定会话                    |
| `new_session`    | 为当前项目创建新会话                   |


#### 消息发送类


| 工具              | 功能         |
| --------------- | ---------- |
| `send_message`  | 主动发送消息到 IM |
| `send_progress` | 发送进度/状态更新  |


#### 命令执行类


| 工具                | 功能                | 安全约束             |
| ----------------- | ----------------- | ---------------- |
| `execute_command` | 在项目目录中执行 shell 命令 | 路径不可逃逸 workspace |


#### 服务启动类


| 工具               | 功能                  |
| ---------------- | ------------------- |
| `start_service`  | 在项目目录中启动后台服务，记录 PID |
| `stop_service`   | 停止指定服务              |
| `service_status` | 查看运行中的服务            |
| `service_logs`   | 查看服务日志              |


#### 工具安装类


| 工具              | 功能                          |
| --------------- | --------------------------- |
| `install_skill` | 为 Claude Code 安装 skill      |
| `install_mcp`   | 为 Claude Code 配置 MCP server |


### 10.2 工具安全原则

所有命令执行类工具在执行前进行路径校验:

```python
def validate_workspace_boundary(path: str, workspace_root: str) -> bool:
    resolved = os.path.realpath(path)
    return resolved.startswith(os.path.realpath(workspace_root))
```

---

## 十一、多项目并发

### 11.1 并发模型

```
┌───────────────────────────────────────────────┐
│                 主 Agent                       │
│                                               │
│  收到消息 → 识别目标项目 → 分发到项目 Session   │
└──────────────────┬────────────────────────────┘
                   │
       ┌───────────┼───────────┐
       ▼           ▼           ▼
   项目 A       项目 B      项目 C
   (RUNNING)   (RUNNING)   (IDLE)
       │           │
       │           │    ← 各项目独立的 ClaudeSDKClient
       │           │    ← 各项目独立的 asyncio Task
       │           │
   同一项目内     同一项目内
   串行执行      串行执行
```

- 每个项目的 Claude Code 会话串行执行（避免同一项目多个操作冲突）
- 不同项目之间可以并行（独立的 `ClaudeSDKClient` 实例）

### 11.2 消息路由

Claude Code 的 Hook 回调通过 `session_id` 映射回项目:

```python
class SessionProjectMap:
    """session_id → project 映射"""

    def __init__(self):
        self._map: dict[str, str] = {}  # session_id → project_name

    def register(self, session_id: str, project_name: str):
        self._map[session_id] = project_name

    def get_project(self, session_id: str) -> str | None:
        return self._map.get(session_id)
```

多项目并发时，IM 消息前缀标注项目来源:

```
[myapp] ✅ 任务完成: 实现了 JWT 认证模块
[backend-api] ⚠️ 请求确认: rm -rf dist/ [#2]
```

---

## 十二、费用追踪

### 12.1 双层费用


| 费用来源                  | 追踪方式                                     |
| --------------------- | ---------------------------------------- |
| 主 Agent (pydantic-ai) | pydantic-ai 的 `usage` 信息                 |
| Claude Code (SDK)     | `ResultMessage.total_cost_usd` + `usage` |


### 12.2 费用管理

```python
class CostTracker:
    def __init__(self, budget_limit: float | None = None):
        self.total_agent_cost: float = 0.0
        self.total_claude_code_cost: float = 0.0
        self.budget_limit = budget_limit

    def track_claude_code(self, result: ResultMessage):
        if result.total_cost_usd:
            self.total_claude_code_cost += result.total_cost_usd
        self._check_budget()

    def _check_budget(self):
        total = self.total_agent_cost + self.total_claude_code_cost
        if self.budget_limit and total > self.budget_limit * 0.8:
            # 通知用户费用预警
            ...
```

可以在 `ClaudeAgentOptions` 中设置 `max_budget_usd` 做单会话费用上限。

---

## 十三、全局配置

`~/.chatcc/config.yaml`:

```yaml
# 消息渠道
channel:
  type: telegram  # telegram / discord / cli
  telegram:
    token: "${TELEGRAM_BOT_TOKEN}"
    allowed_users:
      - "123456789"
  discord:
    token: "${DISCORD_BOT_TOKEN}"
    allowed_guilds: []

# 主 Agent
agent:
  # 当前使用的供应商名称 (对应 providers 中的 key)
  active_provider: "anthropic"

  # AI 供应商配置 (支持多个，按名称切换)
  providers:
    anthropic:
      name: "Anthropic"
      model: "claude-haiku-4-20250414"
      api_key: "${ANTHROPIC_API_KEY}"
      # base_url 不填则使用官方默认地址
    openai:
      name: "OpenAI"
      model: "gpt-4o-mini"
      api_key: "${OPENAI_API_KEY}"
    custom-llm:
      name: "自建服务"
      model: "my-model-v1"
      api_key: "${CUSTOM_API_KEY}"
      base_url: "https://my-llm.example.com/v1"

  persona: "default"  # 人设文件名 (personas/default.md)
  memory:
    summarize_threshold: 50          # 消息数触发压缩
    summarize_token_percent: 75      # token 占比触发压缩
    recent_daily_notes: 3            # 注入最近几天的笔记

# 安全
security:
  workspace_root: "/home/user/projects"  # 所有项目必须在此目录下
  dangerous_tool_patterns:
    Bash:
      - "\\brm\\s"
      - "\\bsudo\\b"
      - "\\bcurl\\b.*\\|\\s*bash"

# Claude Code 默认选项
claude_defaults:
  permission_mode: "acceptEdits"
  setting_sources:
    - "project"
  model: null

# 费用
budget:
  daily_limit: null       # 每日费用上限 (null = 不限制)
  session_limit: null     # 单次会话费用上限
```

---

## 十四、项目结构

```
chatcc/
├── pyproject.toml
├── README.md
├── src/
│   └── chatcc/
│       ├── __init__.py
│       ├── main.py                  # 入口
│       ├── config.py                # 配置加载
│       │
│       ├── channel/                 # 消息渠道层
│       │   ├── __init__.py
│       │   ├── base.py              # MessageChannel 抽象接口
│       │   ├── message.py           # InboundMessage, OutboundMessage, RichMessage, 元素类型
│       │   ├── telegram.py          # Telegram 渠道 + render 实现
│       │   ├── discord.py           # Discord 渠道 + render 实现
│       │   ├── wechat.py            # WeChat 渠道 + render 实现
│       │   └── cli.py               # CLI 渠道 + render 实现
│       │
│       ├── router/                  # 消息路由
│       │   ├── __init__.py
│       │   └── router.py            # MessageRouter
│       │
│       ├── agent/                   # 主 Agent
│       │   ├── __init__.py
│       │   ├── dispatcher.py        # pydantic-ai Agent 定义
│       │   ├── provider.py          # 多供应商管理 (ProviderConfig, build_model)
│       │   ├── prompt.py            # 系统提示词构建
│       │   └── formatter.py         # 输出格式化
│       │
│       ├── memory/                  # 记忆系统
│       │   ├── __init__.py
│       │   ├── history.py           # 会话历史 (JSONL)
│       │   ├── summary.py           # 会话摘要/压缩
│       │   └── longterm.py          # 长期记忆管理
│       │
│       ├── project/                 # 项目管理
│       │   ├── __init__.py
│       │   ├── manager.py           # ProjectManager
│       │   └── models.py            # Project, ProjectConfig
│       │
│       ├── claude/                  # Claude Code 会话管理
│       │   ├── __init__.py
│       │   ├── session.py           # ProjectSession (ClaudeSDKClient 封装)
│       │   ├── hooks.py             # Hook 回调实现
│       │   └── events.py            # 事件处理 (任务完成/失败/通知)
│       │
│       ├── approval/                # 安全审批
│       │   ├── __init__.py
│       │   ├── table.py             # PendingApprovalTable
│       │   └── risk.py              # 风险评估 (assess_risk)
│       │
│       ├── tools/                   # 主 Agent 工具
│       │   ├── __init__.py
│       │   ├── project_tools.py     # 项目管理工具
│       │   ├── session_tools.py     # Claude 会话工具
│       │   ├── command_tools.py     # 命令执行工具
│       │   ├── service_tools.py     # 服务启动工具
│       │   └── install_tools.py     # 工具安装 (skill/mcp)
│       │
│       ├── cost/                    # 费用追踪
│       │   ├── __init__.py
│       │   └── tracker.py
│       │
│       └── personas/                # 人设提示词
│           └── default.md
│
├── tests/
│   └── ...
│
└── docs/
    ├── architecture.md              # 本文档
    ├── claude-agent-sdk.md
    └── agent_architecture_design.md
```

---

## 十五、数据流总览

```
用户 IM 消息
  │
  ▼
① 渠道接收 → InboundMessage
  │
  ▼
② MessageRouter 路由
  ├── 快捷命令 → 直接处理 (不走 LLM)
  └── 普通消息 ↓
  │
  ▼
③ 主 Agent (pydantic-ai)
  ├── 加载记忆上下文 (会话历史 + 摘要 + 长期记忆 + 工作记忆)
  ├── 组装 system prompt (人设 + 动态状态 + 记忆)
  ├── LLM 调用 (轻量模型)
  └── 决策: 调用哪个工具
  │
  ▼
④ 工具执行
  ├── 项目管理工具 → ProjectManager → 直接返回结果
  ├── Claude 会话工具 → ProjectSession.send_task(prompt)
  │     │
  │     ▼
  │   ⑤ Claude Code 执行
  │     ├── Hook: PreToolUse → 安全检查
  │     │     └── 危险操作 → ApprovalTable → IM 确认 → 等待
  │     ├── Hook: Notification → 转发 IM (进度)
  │     ├── Hook: PostToolUse → 更新状态
  │     └── ResultMessage → 任务完成
  │           ├── 费用追踪
  │           └── 结果送回主 Agent
  │
  ├── 命令执行工具 → 路径校验 → subprocess → 返回结果
  └── 其他工具 → 直接执行 → 返回结果
  │
  ▼
⑥ 主 Agent 格式化响应
  │
  ▼
⑦ 渠道发送 → OutboundMessage → IM
  │
  ▼
⑧ 异步: 检查是否需要压缩会话历史
  └── 超阈值 → 生成摘要 → 提取长期记忆 → 截断历史
```

---

## 十六、MVP 优先级

按实现优先级排序:


| 优先级 | 模块               | 说明                   |
| --- | ---------------- | -------------------- |
| P0  | 项目结构 + 配置        | 骨架搭建                 |
| P0  | 消息渠道 (CLI)       | 先用 CLI 渠道调试          |
| P0  | 主 Agent + 基础工具   | pydantic-ai 调度核心     |
| P0  | Claude Code 会话管理 | ClaudeSDKClient 封装   |
| P1  | 安全审批系统           | ApprovalTable + 风险评估 |
| P1  | 项目管理             | 创建/列出/切换             |
| P1  | 会话历史 + 压缩        | 主 Agent 记忆           |
| P2  | 消息渠道 (Telegram)  | 第一个 IM 渠道            |
| P2  | 长期记忆             | MEMORY.md + 每日笔记     |
| P2  | 费用追踪             | 统计 + 预警              |
| P3  | 多项目并发            | 跨项目并行                |
| P3  | 服务管理             | 启动/停止/日志             |
| P3  | 工具安装             | skill/mcp            |
| P3  | 消息渠道 (Discord)   | 更多渠道                 |


