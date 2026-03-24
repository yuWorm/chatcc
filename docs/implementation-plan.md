# ChatCC 实现计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于 architecture.md 规范，按 MVP 优先级从零实现 ChatCC 调度系统，消息渠道优先实现 Telegram 和飞书。

**Architecture:** 三层架构 — IM 渠道层 (统一接口) → 消息路由 (快捷命令拦截) → 主 Agent (pydantic-ai 调度) → Claude Code 会话管理 (claude-agent-sdk)。所有组件通过明确定义的接口交互，渠道层与业务逻辑完全解耦。

**Tech Stack:**
- Python 3.12+ / uv 包管理
- pydantic-ai (主 Agent 框架)
- claude-agent-sdk (Claude Code 交互)
- python-telegram-bot v21+ (Telegram 渠道)
- lark-oapi v1.5+ (飞书渠道, WebSocket 长连接)
- PyYAML (配置文件)
- JSONL (会话历史持久化)

**参考文档:**
- `docs/architecture.md` — 完整架构设计
- `docs/claude-agent-sdk.md` — Claude Agent SDK API 参考
- `docs/agent_architecture_design.md` — Agent Loop 设计模式参考

---

## Chunk 1: P0 — 项目骨架 + 配置系统

### Task 1: 项目初始化

**Files:**
- Create: `pyproject.toml`
- Create: `src/chatcc/__init__.py`
- Create: `src/chatcc/main.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: 创建 pyproject.toml**

```toml
[project]
name = "chatcc"
version = "0.1.0"
description = "IM-controlled Claude Code orchestration system"
requires-python = ">=3.12"
dependencies = [
    "pydantic-ai",
    "claude-agent-sdk",
    "pyyaml",
    "python-telegram-bot",
    "lark-oapi",
    "click",
]

[project.scripts]
chatcc = "chatcc.main:cli"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/chatcc"]

[project.optional-dependencies]
dev = [
    "pytest",
    "pytest-asyncio",
    "ruff",
]
```

- [ ] **Step 2: 初始化 uv 环境**

Run: `cd /Volumes/WorkSpace/Projects/Idea/chatcc && uv venv && uv pip install -e ".[dev]"`
Expected: 虚拟环境创建成功，依赖安装完成

- [ ] **Step 3: 创建基础入口文件**

`src/chatcc/__init__.py`:
```python
"""ChatCC - IM-controlled Claude Code orchestration system."""
```

`src/chatcc/main.py`:
```python
import asyncio
import click


@click.group()
def cli():
    """ChatCC - 通过 IM 控制 Claude Code"""
    pass


@cli.command()
def run():
    """启动 ChatCC"""
    from chatcc.app import Application
    asyncio.run(Application().start())


@cli.command()
@click.option("--channel", default=None, help="指定渠道")
def auth(channel: str | None):
    """渠道认证"""
    click.echo(f"TODO: auth for channel={channel}")


if __name__ == "__main__":
    cli()
```

`tests/__init__.py`: 空文件

- [ ] **Step 4: 验证项目结构**

Run: `cd /Volumes/WorkSpace/Projects/Idea/chatcc && uv run python -c "import chatcc; print('OK')"`
Expected: 输出 `OK`

- [ ] **Step 5: Commit**

```bash
git init
git add .
git commit -m "chore: initialize project structure with uv and pyproject.toml"
```

---

### Task 2: 配置系统

**Files:**
- Create: `src/chatcc/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: 写 config 测试**

`tests/test_config.py`:
```python
import pytest
from pathlib import Path
from chatcc.config import (
    AppConfig,
    ChannelConfig,
    AgentConfig,
    ProviderConfig,
    SecurityConfig,
    load_config,
)


def test_default_config():
    """默认配置应该包含合理的默认值"""
    config = AppConfig()
    assert config.channel.type == "cli"
    assert config.agent.active_provider == "anthropic"
    assert config.security.workspace_root is not None


def test_load_config_from_yaml(tmp_path):
    """从 YAML 文件加载配置"""
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
channel:
  type: telegram
  telegram:
    token: "test-token"
    allowed_users:
      - "123"

agent:
  active_provider: anthropic
  providers:
    anthropic:
      name: Anthropic
      model: claude-haiku-4-20250414
      api_key: "sk-test"
""")
    config = load_config(config_file)
    assert config.channel.type == "telegram"
    assert config.channel.telegram["token"] == "test-token"
    assert config.agent.providers["anthropic"].model == "claude-haiku-4-20250414"


def test_env_var_expansion(tmp_path, monkeypatch):
    """环境变量引用应该被正确展开"""
    monkeypatch.setenv("TEST_TOKEN", "my-secret-token")
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
channel:
  type: telegram
  telegram:
    token: "${TEST_TOKEN}"
    allowed_users: []
""")
    config = load_config(config_file)
    assert config.channel.telegram["token"] == "my-secret-token"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL (模块不存在)

- [ ] **Step 3: 实现配置模块**

`src/chatcc/config.py`:
```python
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


CHATCC_HOME = Path.home() / ".chatcc"


@dataclass
class ProviderConfig:
    name: str = ""
    model: str = ""
    api_key: str = ""
    base_url: str | None = None


@dataclass
class AgentConfig:
    active_provider: str = "anthropic"
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    persona: str = "default"
    memory: dict[str, Any] = field(default_factory=lambda: {
        "summarize_threshold": 50,
        "summarize_token_percent": 75,
        "recent_daily_notes": 3,
    })


@dataclass
class ChannelConfig:
    type: str = "cli"
    telegram: dict[str, Any] = field(default_factory=dict)
    feishu: dict[str, Any] = field(default_factory=dict)
    discord: dict[str, Any] = field(default_factory=dict)


@dataclass
class SecurityConfig:
    workspace_root: str = str(Path.home() / "projects")
    dangerous_tool_patterns: dict[str, list[str]] = field(default_factory=lambda: {
        "Bash": [r"\brm\s", r"\bsudo\b", r"\bcurl\b.*\|\s*bash"],
    })


@dataclass
class ClaudeDefaultsConfig:
    permission_mode: str = "acceptEdits"
    setting_sources: list[str] = field(default_factory=lambda: ["project"])
    model: str | None = None


@dataclass
class BudgetConfig:
    daily_limit: float | None = None
    session_limit: float | None = None


@dataclass
class AppConfig:
    channel: ChannelConfig = field(default_factory=ChannelConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    claude_defaults: ClaudeDefaultsConfig = field(default_factory=ClaudeDefaultsConfig)
    budget: BudgetConfig = field(default_factory=BudgetConfig)


_ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


def _expand_env_vars(value: Any) -> Any:
    if isinstance(value, str):
        def replacer(match: re.Match) -> str:
            return os.environ.get(match.group(1), match.group(0))
        return _ENV_VAR_PATTERN.sub(replacer, value)
    if isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env_vars(item) for item in value]
    return value


def _dict_to_dataclass(cls: type, data: dict) -> Any:
    """递归地将 dict 转为 dataclass 实例，支持嵌套 dataclass 和 dict[str, dataclass]"""
    import dataclasses

    if not dataclasses.is_dataclass(cls):
        return data

    field_types = {f.name: f.type for f in dataclasses.fields(cls)}
    kwargs = {}
    for key, value in data.items():
        if key not in field_types:
            continue
        ft = field_types[key]
        # 处理 dict[str, ProviderConfig] 这种类型
        if isinstance(value, dict) and ft == "dict[str, ProviderConfig]":
            kwargs[key] = {
                k: ProviderConfig(**v) if isinstance(v, dict) else v
                for k, v in value.items()
            }
        elif isinstance(value, dict) and hasattr(cls, "__dataclass_fields__"):
            # 尝试获取字段对应的 dataclass 类型
            resolved = _resolve_field_type(cls, key)
            if resolved and dataclasses.is_dataclass(resolved):
                kwargs[key] = _dict_to_dataclass(resolved, value)
            else:
                kwargs[key] = value
        else:
            kwargs[key] = value
    return cls(**kwargs)


def _resolve_field_type(cls: type, field_name: str) -> type | None:
    """尝试解析字段的实际类型"""
    import dataclasses
    type_map = {
        "ChannelConfig": ChannelConfig,
        "AgentConfig": AgentConfig,
        "SecurityConfig": SecurityConfig,
        "ClaudeDefaultsConfig": ClaudeDefaultsConfig,
        "BudgetConfig": BudgetConfig,
    }
    for f in dataclasses.fields(cls):
        if f.name == field_name:
            type_str = f.type if isinstance(f.type, str) else getattr(f.type, "__name__", "")
            return type_map.get(type_str)
    return None


def load_config(path: Path | None = None) -> AppConfig:
    if path is None:
        path = CHATCC_HOME / "config.yaml"

    if not path.exists():
        return AppConfig()

    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    expanded = _expand_env_vars(raw)
    return _dict_to_dataclass(AppConfig, expanded)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_config.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/chatcc/config.py tests/test_config.py
git commit -m "feat: add configuration system with YAML loading and env var expansion"
```

---

## Chunk 2: P0 — 消息模型 + 渠道抽象接口 + CLI 渠道

### Task 3: 消息模型定义

**Files:**
- Create: `src/chatcc/channel/__init__.py`
- Create: `src/chatcc/channel/message.py`
- Create: `tests/test_message.py`

- [ ] **Step 1: 写消息模型测试**

`tests/test_message.py`:
```python
from chatcc.channel.message import (
    InboundMessage,
    OutboundMessage,
    RichMessage,
    TextElement,
    CodeElement,
    ActionButton,
    ActionGroup,
    ProgressElement,
    DividerElement,
)


def test_inbound_message():
    msg = InboundMessage(sender_id="u1", content="hello", chat_id="c1")
    assert msg.sender_id == "u1"
    assert msg.media is None


def test_outbound_message_str():
    msg = OutboundMessage(chat_id="c1", content="hello")
    assert isinstance(msg.content, str)


def test_rich_message():
    rich = RichMessage(
        elements=[
            TextElement(content="请确认操作:"),
            CodeElement(code="rm -rf dist/", language="bash"),
            ActionGroup(buttons=[
                ActionButton(label="允许", command="/y 1"),
                ActionButton(label="拒绝", command="/n 1"),
            ]),
        ],
        project_tag="myapp",
    )
    assert len(rich.elements) == 3
    assert rich.project_tag == "myapp"


def test_outbound_message_rich():
    rich = RichMessage(elements=[TextElement(content="test")])
    msg = OutboundMessage(chat_id="c1", content=rich)
    assert isinstance(msg.content, RichMessage)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_message.py -v`
Expected: FAIL

- [ ] **Step 3: 实现消息模型**

`src/chatcc/channel/__init__.py`:
```python
from chatcc.channel.message import (
    InboundMessage,
    OutboundMessage,
    RichMessage,
    TextElement,
    CodeElement,
    ActionButton,
    ActionGroup,
    ProgressElement,
    DividerElement,
    MessageElement,
)
from chatcc.channel.base import MessageChannel

__all__ = [
    "InboundMessage",
    "OutboundMessage",
    "RichMessage",
    "TextElement",
    "CodeElement",
    "ActionButton",
    "ActionGroup",
    "ProgressElement",
    "DividerElement",
    "MessageElement",
    "MessageChannel",
]
```

`src/chatcc/channel/message.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class InboundMessage:
    sender_id: str
    content: str
    chat_id: str
    media: list[str] | None = None
    raw: Any = None


@dataclass
class TextElement:
    content: str


@dataclass
class CodeElement:
    code: str
    language: str = ""


@dataclass
class ActionButton:
    label: str
    command: str


@dataclass
class ActionGroup:
    buttons: list[ActionButton]


@dataclass
class ProgressElement:
    description: str
    project: str = ""


@dataclass
class DividerElement:
    pass


MessageElement = TextElement | CodeElement | ActionGroup | ProgressElement | DividerElement


@dataclass
class RichMessage:
    elements: list[MessageElement]
    reply_to: str | None = None
    project_tag: str | None = None


@dataclass
class OutboundMessage:
    chat_id: str
    content: str | RichMessage
    reply_to: str | None = None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_message.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/chatcc/channel/ tests/test_message.py
git commit -m "feat: add message models (InboundMessage, OutboundMessage, RichMessage)"
```

---

### Task 4: MessageChannel 抽象接口

**Files:**
- Create: `src/chatcc/channel/base.py`
- Create: `tests/test_channel_base.py`

- [ ] **Step 1: 写抽象接口测试**

`tests/test_channel_base.py`:
```python
import pytest
from chatcc.channel.base import MessageChannel
from chatcc.channel.message import InboundMessage, OutboundMessage, RichMessage


def test_cannot_instantiate_abstract():
    """MessageChannel 不可直接实例化"""
    with pytest.raises(TypeError):
        MessageChannel()


def test_concrete_implementation():
    """具体实现必须实现所有抽象方法"""

    class DummyChannel(MessageChannel):
        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

        async def send(self, message: OutboundMessage) -> None:
            pass

        def render(self, message: RichMessage):
            return str(message)

        def on_message(self, callback) -> None:
            pass

        def is_authenticated(self) -> bool:
            return True

    channel = DummyChannel()
    assert channel.is_authenticated()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_channel_base.py -v`
Expected: FAIL

- [ ] **Step 3: 实现抽象接口**

`src/chatcc/channel/base.py`:
```python
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

from chatcc.channel.message import InboundMessage, OutboundMessage, RichMessage


class MessageChannel(ABC):

    @abstractmethod
    async def start(self) -> None:
        """启动渠道连接"""

    @abstractmethod
    async def stop(self) -> None:
        """断开连接，清理资源"""

    @abstractmethod
    async def send(self, message: OutboundMessage) -> None:
        """发送消息到渠道"""

    @abstractmethod
    def render(self, message: RichMessage) -> Any:
        """将 RichMessage 转为渠道原生消息格式"""

    @abstractmethod
    def on_message(self, callback: Callable[[InboundMessage], Awaitable[None]]) -> None:
        """注册消息回调"""

    def register_auth_commands(self, cli_group: Any) -> None:
        """注册渠道认证相关的 CLI 子命令 (可选)"""
        pass

    @abstractmethod
    def is_authenticated(self) -> bool:
        """检查渠道是否已完成认证"""
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_channel_base.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/chatcc/channel/base.py tests/test_channel_base.py
git commit -m "feat: add MessageChannel abstract interface"
```

---

### Task 5: CLI 渠道实现

**Files:**
- Create: `src/chatcc/channel/cli.py`
- Create: `tests/test_channel_cli.py`

- [ ] **Step 1: 写 CLI 渠道测试**

`tests/test_channel_cli.py`:
```python
import pytest
import asyncio
from chatcc.channel.cli import CliChannel
from chatcc.channel.message import (
    OutboundMessage,
    RichMessage,
    TextElement,
    CodeElement,
    ActionGroup,
    ActionButton,
    DividerElement,
)


def test_cli_always_authenticated():
    channel = CliChannel()
    assert channel.is_authenticated()


def test_cli_render_rich_message():
    channel = CliChannel()
    rich = RichMessage(
        elements=[
            TextElement(content="Claude Code 请求执行:"),
            CodeElement(code="rm -rf dist/", language="bash"),
            DividerElement(),
            ActionGroup(buttons=[
                ActionButton(label="允许", command="/y 1"),
                ActionButton(label="拒绝", command="/n 1"),
            ]),
        ],
        project_tag="myapp",
    )
    rendered = channel.render(rich)
    assert "[myapp]" in rendered
    assert "rm -rf dist/" in rendered
    assert "/y 1" in rendered


@pytest.mark.asyncio
async def test_cli_on_message_callback():
    channel = CliChannel()
    received = []

    async def handler(msg):
        received.append(msg)

    channel.on_message(handler)
    assert channel._callback is not None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_channel_cli.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 CLI 渠道**

`src/chatcc/channel/cli.py`:
```python
from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from typing import Any

from chatcc.channel.base import MessageChannel
from chatcc.channel.message import (
    ActionGroup,
    CodeElement,
    DividerElement,
    InboundMessage,
    OutboundMessage,
    ProgressElement,
    RichMessage,
    TextElement,
)


class CliChannel(MessageChannel):
    def __init__(self):
        self._callback: Callable[[InboundMessage], Awaitable[None]] | None = None
        self._running = False
        self._read_task: asyncio.Task | None = None

    async def start(self) -> None:
        self._running = True
        self._read_task = asyncio.create_task(self._read_loop())

    async def stop(self) -> None:
        self._running = False
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass

    async def send(self, message: OutboundMessage) -> None:
        if isinstance(message.content, RichMessage):
            text = self.render(message.content)
        else:
            text = str(message.content)
        print(text, flush=True)

    def render(self, message: RichMessage) -> str:
        parts: list[str] = []

        if message.project_tag:
            parts.append(f"[{message.project_tag}]")

        for element in message.elements:
            match element:
                case TextElement(content=content):
                    parts.append(content)
                case CodeElement(code=code, language=lang):
                    parts.append(f"  $ {code}")
                case ActionGroup(buttons=buttons):
                    hints = " | ".join(f"{b.command} {b.label}" for b in buttons)
                    parts.append(f"  → {hints}")
                case ProgressElement(description=desc, project=proj):
                    tag = f"[{proj}] " if proj else ""
                    parts.append(f"  ⏳ {tag}{desc}")
                case DividerElement():
                    parts.append("  " + "─" * 40)

        return "\n".join(parts)

    def on_message(self, callback: Callable[[InboundMessage], Awaitable[None]]) -> None:
        self._callback = callback

    def is_authenticated(self) -> bool:
        return True

    async def _read_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while self._running:
            try:
                line = await loop.run_in_executor(None, sys.stdin.readline)
                line = line.strip()
                if not line:
                    continue
                if self._callback:
                    msg = InboundMessage(
                        sender_id="cli-user",
                        content=line,
                        chat_id="cli",
                    )
                    await self._callback(msg)
            except (EOFError, KeyboardInterrupt):
                break
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_channel_cli.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/chatcc/channel/cli.py tests/test_channel_cli.py
git commit -m "feat: add CLI channel implementation for local debugging"
```

---

### Task 6: 渠道工厂

**Files:**
- Create: `src/chatcc/channel/factory.py`
- Create: `tests/test_channel_factory.py`

- [ ] **Step 1: 写工厂测试**

`tests/test_channel_factory.py`:
```python
import pytest
from chatcc.channel.factory import create_channel
from chatcc.channel.cli import CliChannel
from chatcc.config import ChannelConfig


def test_create_cli_channel():
    config = ChannelConfig(type="cli")
    channel = create_channel(config)
    assert isinstance(channel, CliChannel)


def test_create_unknown_channel():
    config = ChannelConfig(type="unknown")
    with pytest.raises(ValueError, match="unknown"):
        create_channel(config)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_channel_factory.py -v`
Expected: FAIL

- [ ] **Step 3: 实现渠道工厂**

`src/chatcc/channel/factory.py`:
```python
from __future__ import annotations

from chatcc.channel.base import MessageChannel
from chatcc.config import ChannelConfig


def create_channel(config: ChannelConfig) -> MessageChannel:
    match config.type:
        case "cli":
            from chatcc.channel.cli import CliChannel
            return CliChannel()
        case "telegram":
            from chatcc.channel.telegram import TelegramChannel
            return TelegramChannel(config.telegram)
        case "feishu":
            from chatcc.channel.feishu import FeishuChannel
            return FeishuChannel(config.feishu)
        case _:
            raise ValueError(f"Unknown channel type: {config.type}")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_channel_factory.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/chatcc/channel/factory.py tests/test_channel_factory.py
git commit -m "feat: add channel factory for config-based channel creation"
```

---

## Chunk 3: P0 — 消息路由

### Task 7: MessageRouter

**Files:**
- Create: `src/chatcc/router/__init__.py`
- Create: `src/chatcc/router/router.py`
- Create: `tests/test_router.py`

- [ ] **Step 1: 写路由测试**

`tests/test_router.py`:
```python
import pytest
from chatcc.router.router import MessageRouter
from chatcc.channel.message import InboundMessage


@pytest.fixture
def router():
    return MessageRouter()


@pytest.mark.asyncio
async def test_intercept_y_command(router):
    msg = InboundMessage(sender_id="u1", content="/y 3", chat_id="c1")
    result = await router.route(msg)
    assert result.intercepted is True
    assert result.command == "/y"
    assert result.args == ["3"]


@pytest.mark.asyncio
async def test_intercept_n_command(router):
    msg = InboundMessage(sender_id="u1", content="/n", chat_id="c1")
    result = await router.route(msg)
    assert result.intercepted is True
    assert result.command == "/n"


@pytest.mark.asyncio
async def test_intercept_pending(router):
    msg = InboundMessage(sender_id="u1", content="/pending", chat_id="c1")
    result = await router.route(msg)
    assert result.intercepted is True


@pytest.mark.asyncio
async def test_intercept_stop(router):
    msg = InboundMessage(sender_id="u1", content="/stop", chat_id="c1")
    result = await router.route(msg)
    assert result.intercepted is True


@pytest.mark.asyncio
async def test_intercept_status(router):
    msg = InboundMessage(sender_id="u1", content="/status", chat_id="c1")
    result = await router.route(msg)
    assert result.intercepted is True


@pytest.mark.asyncio
async def test_normal_message_not_intercepted(router):
    msg = InboundMessage(sender_id="u1", content="帮我实现登录功能", chat_id="c1")
    result = await router.route(msg)
    assert result.intercepted is False
    assert result.message == msg


@pytest.mark.asyncio
async def test_y_all_command(router):
    msg = InboundMessage(sender_id="u1", content="/y all", chat_id="c1")
    result = await router.route(msg)
    assert result.intercepted is True
    assert result.command == "/y"
    assert result.args == ["all"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_router.py -v`
Expected: FAIL

- [ ] **Step 3: 实现路由器**

`src/chatcc/router/__init__.py`: 空文件

`src/chatcc/router/router.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field

from chatcc.channel.message import InboundMessage


@dataclass
class RouteResult:
    intercepted: bool
    command: str | None = None
    args: list[str] = field(default_factory=list)
    message: InboundMessage | None = None


class MessageRouter:
    INTERCEPT_COMMANDS = frozenset({"/y", "/n", "/pending", "/stop", "/status"})

    async def route(self, message: InboundMessage) -> RouteResult:
        parts = message.content.strip().split()
        if not parts:
            return RouteResult(intercepted=False, message=message)

        cmd = parts[0].lower()
        if cmd in self.INTERCEPT_COMMANDS:
            return RouteResult(
                intercepted=True,
                command=cmd,
                args=parts[1:],
            )

        return RouteResult(intercepted=False, message=message)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_router.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/chatcc/router/ tests/test_router.py
git commit -m "feat: add MessageRouter with shortcut command interception"
```

---

## Chunk 4: P0 — 主 Agent 核心

### Task 8: Provider 管理 (多供应商支持)

**Files:**
- Create: `src/chatcc/agent/__init__.py`
- Create: `src/chatcc/agent/provider.py`
- Create: `tests/test_provider.py`

- [ ] **Step 1: 写 provider 测试**

`tests/test_provider.py`:
```python
import pytest
from chatcc.agent.provider import build_model_from_config
from chatcc.config import ProviderConfig


def test_build_official_anthropic():
    providers = {
        "anthropic": ProviderConfig(
            name="Anthropic",
            model="claude-haiku-4-20250414",
            api_key="sk-test",
        )
    }
    model = build_model_from_config(providers, "anthropic")
    assert model == "anthropic:claude-haiku-4-20250414"


def test_build_official_openai():
    providers = {
        "openai": ProviderConfig(
            name="OpenAI",
            model="gpt-4o-mini",
            api_key="sk-test",
        )
    }
    model = build_model_from_config(providers, "openai")
    assert model == "openai:gpt-4o-mini"


def test_build_custom_provider():
    providers = {
        "custom": ProviderConfig(
            name="Custom",
            model="my-model",
            api_key="sk-test",
            base_url="https://api.custom.com/v1",
        )
    }
    model = build_model_from_config(providers, "custom")
    # 自定义供应商应返回 OpenAIModel 实例
    assert hasattr(model, "model_name")


def test_unknown_provider():
    with pytest.raises(KeyError):
        build_model_from_config({}, "nonexistent")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_provider.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 provider 模块**

`src/chatcc/agent/__init__.py`: 空文件

`src/chatcc/agent/provider.py`:
```python
from __future__ import annotations

from chatcc.config import ProviderConfig


OFFICIAL_PREFIXES = {
    "anthropic": "anthropic",
    "openai": "openai",
    "google": "google-gla",
}


def build_model_from_config(
    providers: dict[str, ProviderConfig],
    active: str,
):
    provider = providers[active]

    if provider.base_url:
        from pydantic_ai.models.openai import OpenAIModel
        from pydantic_ai.providers.openai import OpenAIProvider

        return OpenAIModel(
            provider.model,
            provider=OpenAIProvider(
                base_url=provider.base_url,
                api_key=provider.api_key,
            ),
        )

    prefix = OFFICIAL_PREFIXES.get(active, active)
    return f"{prefix}:{provider.model}"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_provider.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/chatcc/agent/ tests/test_provider.py
git commit -m "feat: add multi-provider model builder for main agent"
```

---

### Task 9: 系统提示词

**Files:**
- Create: `src/chatcc/agent/prompt.py`
- Create: `src/chatcc/personas/default.md`
- Create: `tests/test_prompt.py`

- [ ] **Step 1: 创建默认人设文件**

`src/chatcc/personas/default.md`:
```markdown
你是 ChatCC 的主控助手。你的职责是：

1. **理解用户意图**：用户通过 IM 发送的消息可能是开发指令、项目管理操作、或日常对话
2. **调度 Claude Code**：将开发相关的任务转发给对应项目的 Claude Code 会话
3. **管理项目状态**：跟踪各项目的当前状态、活跃会话、待确认操作
4. **安全把关**：危险操作需要用户确认

**你不应该**：
- 试图理解或分析代码内容
- 自己执行编程任务
- 跳过安全审批流程

**回复风格**：
- 简洁直接，不啰嗦
- 中文回复（除非用户用英文）
- 操作结果用清晰的状态标记
```

- [ ] **Step 2: 写提示词构建测试**

`tests/test_prompt.py`:
```python
from chatcc.agent.prompt import build_system_prompt


def test_build_system_prompt_contains_persona():
    prompt = build_system_prompt(
        persona_name="default",
        default_project="myapp",
        active_count=2,
        pending_count=1,
    )
    assert "ChatCC" in prompt
    assert "myapp" in prompt
    assert "2" in prompt


def test_build_system_prompt_no_project():
    prompt = build_system_prompt(
        persona_name="default",
        default_project=None,
        active_count=0,
        pending_count=0,
    )
    assert "无" in prompt or "None" in prompt or "未设置" in prompt
```

- [ ] **Step 3: 运行测试确认失败**

Run: `uv run pytest tests/test_prompt.py -v`
Expected: FAIL

- [ ] **Step 4: 实现提示词构建**

`src/chatcc/agent/prompt.py`:
```python
from __future__ import annotations

from datetime import datetime
from pathlib import Path


PERSONAS_DIR = Path(__file__).parent.parent / "personas"


def load_persona(name: str = "default") -> str:
    path = PERSONAS_DIR / f"{name}.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def build_system_prompt(
    persona_name: str = "default",
    default_project: str | None = None,
    active_count: int = 0,
    pending_count: int = 0,
    memory_context: str = "",
) -> str:
    static = load_persona(persona_name)

    dynamic_lines = [
        f"当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"当前默认项目: {default_project or '未设置'}",
        f"活跃项目数: {active_count}",
        f"待确认操作: {pending_count}",
    ]
    dynamic = "\n".join(dynamic_lines)

    parts = [static, "\n---\n", dynamic]
    if memory_context:
        parts.extend(["\n---\n", memory_context])

    return "\n".join(parts)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/test_prompt.py -v`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add src/chatcc/agent/prompt.py src/chatcc/personas/ tests/test_prompt.py
git commit -m "feat: add system prompt builder with persona loading"
```

---

### Task 10: 主 Agent Dispatcher

**Files:**
- Create: `src/chatcc/agent/dispatcher.py`
- Create: `tests/test_dispatcher.py`

- [ ] **Step 1: 写 dispatcher 测试**

`tests/test_dispatcher.py`:
```python
import pytest
from chatcc.agent.dispatcher import Dispatcher


def test_dispatcher_init():
    """Dispatcher 初始化不应抛出异常"""
    dispatcher = Dispatcher(
        provider_name="test",
        model_id="anthropic:claude-haiku-4-20250414",
        persona="default",
    )
    assert dispatcher.agent is not None


def test_dispatcher_has_tools():
    """Dispatcher 应注册了工具"""
    dispatcher = Dispatcher(
        provider_name="test",
        model_id="anthropic:claude-haiku-4-20250414",
        persona="default",
    )
    # pydantic-ai Agent 的 _function_tools 属性
    tool_names = list(dispatcher.agent._function_tools.keys())
    assert len(tool_names) > 0
```

注意: 完整的 Agent 工具在后续 Task 实现，此处只验证 Dispatcher 骨架。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_dispatcher.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 Dispatcher**

`src/chatcc/agent/dispatcher.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import Agent, RunContext

from chatcc.agent.prompt import build_system_prompt


@dataclass
class AgentDeps:
    """主 Agent 运行时依赖"""
    default_project: str | None = None
    active_projects: int = 0
    pending_approvals: int = 0
    send_fn: Any = None  # Callable for sending messages back to channel


class Dispatcher:
    def __init__(
        self,
        provider_name: str,
        model_id: str | Any,
        persona: str = "default",
    ):
        self.provider_name = provider_name
        self.persona = persona

        self.agent = Agent(
            model_id,
            deps_type=AgentDeps,
            instructions=self._build_instructions,
        )

        self._register_tools()

    def _build_instructions(self, ctx: RunContext[AgentDeps]) -> str:
        return build_system_prompt(
            persona_name=self.persona,
            default_project=ctx.deps.default_project,
            active_count=ctx.deps.active_projects,
            pending_count=ctx.deps.pending_approvals,
        )

    def _register_tools(self):
        @self.agent.tool_plain
        def send_message(content: str) -> str:
            """发送消息到 IM 渠道 (用于主动通知)"""
            return f"[send_message] {content}"

        @self.agent.tool_plain
        def get_status() -> str:
            """获取当前系统状态"""
            return "系统状态: 正常运行中"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_dispatcher.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/chatcc/agent/dispatcher.py tests/test_dispatcher.py
git commit -m "feat: add main Agent dispatcher with pydantic-ai"
```

---

## Chunk 5: P0 — Claude Code 会话管理

### Task 11: 项目模型

**Files:**
- Create: `src/chatcc/project/__init__.py`
- Create: `src/chatcc/project/models.py`
- Create: `tests/test_project_models.py`

- [ ] **Step 1: 写项目模型测试**

`tests/test_project_models.py`:
```python
from datetime import datetime
from chatcc.project.models import Project, ProjectConfig


def test_project_creation():
    p = Project(name="myapp", path="/home/user/projects/myapp")
    assert p.name == "myapp"
    assert p.is_default is False
    assert isinstance(p.created_at, datetime)


def test_project_config_defaults():
    config = ProjectConfig()
    assert config.permission_mode == "acceptEdits"
    assert "project" in config.setting_sources
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_project_models.py -v`
Expected: FAIL

- [ ] **Step 3: 实现项目模型**

`src/chatcc/project/__init__.py`: 空文件

`src/chatcc/project/models.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ProjectConfig:
    permission_mode: str = "acceptEdits"
    setting_sources: list[str] = field(default_factory=lambda: ["project"])
    model: str | None = None


@dataclass
class Project:
    name: str
    path: str
    created_at: datetime = field(default_factory=datetime.now)
    is_default: bool = False
    config: ProjectConfig = field(default_factory=ProjectConfig)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_project_models.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/chatcc/project/ tests/test_project_models.py
git commit -m "feat: add Project and ProjectConfig models"
```

---

### Task 12: Claude Code 会话封装 (ProjectSession)

**Files:**
- Create: `src/chatcc/claude/__init__.py`
- Create: `src/chatcc/claude/session.py`
- Create: `tests/test_claude_session.py`

- [ ] **Step 1: 写会话封装测试**

`tests/test_claude_session.py`:
```python
import pytest
from chatcc.claude.session import ProjectSession, TaskState
from chatcc.project.models import Project


def test_initial_state():
    project = Project(name="test", path="/tmp/test")
    session = ProjectSession(project)
    assert session.task_state == TaskState.IDLE
    assert session.client is None
    assert session.active_session_id is None


def test_task_state_enum():
    assert TaskState.IDLE.value == "idle"
    assert TaskState.RUNNING.value == "running"
    assert TaskState.COMPLETED.value == "completed"


def test_build_options():
    project = Project(name="test", path="/tmp/test")
    session = ProjectSession(project)
    options = session._build_options()
    assert options.cwd == "/tmp/test"
    assert options.permission_mode == "acceptEdits"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_claude_session.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 ProjectSession**

`src/chatcc/claude/__init__.py`: 空文件

`src/chatcc/claude/session.py`:
```python
from __future__ import annotations

import asyncio
from collections.abc import Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions, HookMatcher

from chatcc.project.models import Project


class TaskState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    INTERRUPTING = "interrupting"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ProjectSession:
    def __init__(
        self,
        project: Project,
        on_notification: Callable[[str, str], Awaitable[None]] | None = None,
        on_permission: Callable[[str, dict], Awaitable[bool]] | None = None,
    ):
        self.project = project
        self.client: ClaudeSDKClient | None = None
        self.active_session_id: str | None = None
        self.task_state: TaskState = TaskState.IDLE
        self._on_notification = on_notification
        self._on_permission = on_permission

    def _build_options(self) -> ClaudeAgentOptions:
        hooks = {}
        if self._on_notification:
            hooks["Notification"] = [HookMatcher(hooks=[self._notification_hook])]

        return ClaudeAgentOptions(
            cwd=self.project.path,
            permission_mode=self.project.config.permission_mode,
            setting_sources=self.project.config.setting_sources,
            can_use_tool=self._permission_handler if self._on_permission else None,
            hooks=hooks if hooks else None,
            resume=self.active_session_id,
            model=self.project.config.model,
        )

    async def ensure_connected(self) -> ClaudeSDKClient:
        if not self.client:
            self.client = ClaudeSDKClient(options=self._build_options())
            await self.client.connect()
        return self.client

    async def send_task(self, prompt: str) -> None:
        client = await self.ensure_connected()
        self.task_state = TaskState.RUNNING
        try:
            await client.query(prompt)
        except Exception:
            self.task_state = TaskState.FAILED
            raise

    async def interrupt(self) -> None:
        if self.client and self.task_state == TaskState.RUNNING:
            self.task_state = TaskState.INTERRUPTING
            await self.client.interrupt()

    async def disconnect(self) -> None:
        if self.client:
            await self.client.disconnect()
            self.client = None

    async def _notification_hook(self, context: Any) -> None:
        if self._on_notification:
            title = getattr(context, "title", "")
            body = getattr(context, "body", "")
            await self._on_notification(self.project.name, f"{title}: {body}")

    async def _permission_handler(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        context: Any,
    ):
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

        if self._on_permission:
            allowed = await self._on_permission(tool_name, input_data)
            if allowed:
                return PermissionResultAllow(updated_input=input_data)
            return PermissionResultDeny(reason="User denied")
        return PermissionResultAllow(updated_input=input_data)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_claude_session.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/chatcc/claude/ tests/test_claude_session.py
git commit -m "feat: add ProjectSession wrapping ClaudeSDKClient lifecycle"
```

---

## Chunk 6: P0 — Application 主入口

### Task 13: Application 整合

**Files:**
- Create: `src/chatcc/app.py`
- Modify: `src/chatcc/main.py`

- [ ] **Step 1: 实现 Application**

`src/chatcc/app.py`:
```python
from __future__ import annotations

import asyncio
import logging
from typing import Any

from chatcc.config import AppConfig, load_config
from chatcc.channel.base import MessageChannel
from chatcc.channel.factory import create_channel
from chatcc.channel.message import InboundMessage, OutboundMessage
from chatcc.router.router import MessageRouter
from chatcc.agent.dispatcher import Dispatcher, AgentDeps
from chatcc.agent.provider import build_model_from_config

logger = logging.getLogger("chatcc")


class Application:
    def __init__(self, config: AppConfig | None = None):
        self.config = config or load_config()
        self.channel: MessageChannel | None = None
        self.router = MessageRouter()
        self.dispatcher: Dispatcher | None = None
        self._running = False

    async def start(self):
        logger.info("Starting ChatCC...")

        if not self._init_channel():
            return

        self._init_dispatcher()
        self.channel.on_message(self._on_message)

        self._running = True
        await self.channel.start()

        logger.info(f"ChatCC running with channel: {self.config.channel.type}")

        try:
            while self._running:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            await self.stop()

    async def stop(self):
        self._running = False
        if self.channel:
            await self.channel.stop()
        logger.info("ChatCC stopped.")

    def _init_channel(self) -> bool:
        self.channel = create_channel(self.config.channel)
        if not self.channel.is_authenticated():
            logger.error(
                f"Channel '{self.config.channel.type}' not authenticated. "
                f"Run: chatcc auth --channel {self.config.channel.type}"
            )
            return False
        return True

    def _init_dispatcher(self):
        model = build_model_from_config(
            self.config.agent.providers,
            self.config.agent.active_provider,
        )
        self.dispatcher = Dispatcher(
            provider_name=self.config.agent.active_provider,
            model_id=model,
            persona=self.config.agent.persona,
        )

    async def _on_message(self, message: InboundMessage):
        result = await self.router.route(message)

        if result.intercepted:
            await self._handle_command(result.command, result.args, message)
        else:
            await self._handle_agent_message(message)

    async def _handle_command(self, command: str, args: list[str], message: InboundMessage):
        match command:
            case "/y" | "/n":
                # TODO: P1 - ApprovalTable integration
                response = f"审批命令 {command} {' '.join(args)} (待实现)"
            case "/pending":
                response = "暂无待确认操作 (待实现)"
            case "/stop":
                response = "停止命令已收到 (待实现)"
            case "/status":
                response = "系统状态: 正常运行中"
            case _:
                response = f"未知命令: {command}"

        await self.channel.send(OutboundMessage(
            chat_id=message.chat_id,
            content=response,
        ))

    async def _handle_agent_message(self, message: InboundMessage):
        if not self.dispatcher:
            return

        deps = AgentDeps(
            default_project=None,
            active_projects=0,
            pending_approvals=0,
        )

        try:
            result = await self.dispatcher.agent.run(
                message.content,
                deps=deps,
            )
            await self.channel.send(OutboundMessage(
                chat_id=message.chat_id,
                content=result.output,
            ))
        except Exception as e:
            logger.exception("Agent error")
            await self.channel.send(OutboundMessage(
                chat_id=message.chat_id,
                content=f"处理消息时出错: {e}",
            ))
```

- [ ] **Step 2: 更新 main.py 入口**

在 `src/chatcc/main.py` 中确认 `run` 命令正确调用 `Application().start()`，并添加 `--config` 选项:

```python
import asyncio
import logging
from pathlib import Path

import click


@click.group()
def cli():
    """ChatCC - 通过 IM 控制 Claude Code"""
    pass


@cli.command()
@click.option("--config", "config_path", default=None, type=click.Path(exists=True))
@click.option("--debug", is_flag=True, default=False)
def run(config_path: str | None, debug: bool):
    """启动 ChatCC"""
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    from chatcc.config import load_config
    from chatcc.app import Application

    config = load_config(Path(config_path) if config_path else None)
    asyncio.run(Application(config).start())


@cli.command()
@click.option("--channel", default=None, help="指定渠道")
def auth(channel: str | None):
    """渠道认证"""
    click.echo(f"TODO: auth for channel={channel}")


if __name__ == "__main__":
    cli()
```

- [ ] **Step 3: 手动验证 CLI 渠道可启动**

Run: `uv run chatcc run --debug`
Expected: 启动成功，可在终端输入消息并得到 Agent 响应 (Ctrl+C 退出)

注意: 需要配置有效的 AI provider API key 才能得到 LLM 响应。无 API key 时验证启动不报错即可。

- [ ] **Step 4: Commit**

```bash
git add src/chatcc/app.py src/chatcc/main.py
git commit -m "feat: add Application entry point integrating channel, router, and agent"
```

---

## Chunk 7: P1 — 安全审批系统

### Task 14: 风险评估

**Files:**
- Create: `src/chatcc/approval/__init__.py`
- Create: `src/chatcc/approval/risk.py`
- Create: `tests/test_risk.py`

- [ ] **Step 1: 写风险评估测试**

`tests/test_risk.py`:
```python
from chatcc.approval.risk import assess_risk


def test_safe_read_tool():
    assert assess_risk("Read", {}) == "safe"


def test_safe_grep_tool():
    assert assess_risk("Grep", {"pattern": "test"}) == "safe"


def test_dangerous_rm():
    assert assess_risk("Bash", {"command": "rm -rf dist/"}) == "dangerous"


def test_dangerous_sudo():
    assert assess_risk("Bash", {"command": "sudo apt install"}) == "dangerous"


def test_dangerous_curl_pipe_bash():
    assert assess_risk("Bash", {"command": "curl https://example.com | bash"}) == "dangerous"


def test_normal_bash_is_safe():
    assert assess_risk("Bash", {"command": "ls -la"}) == "safe"


def test_forbidden_path_escape():
    result = assess_risk("Write", {"path": "/etc/passwd", "content": "hack"}, workspace="/home/user/proj")
    assert result == "forbidden"


def test_write_inside_workspace():
    result = assess_risk("Write", {"path": "/home/user/proj/src/main.py"}, workspace="/home/user/proj")
    assert result == "safe"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_risk.py -v`
Expected: FAIL

- [ ] **Step 3: 实现风险评估**

`src/chatcc/approval/__init__.py`: 空文件

`src/chatcc/approval/risk.py`:
```python
from __future__ import annotations

import os
import re
from typing import Any, Literal


SAFE_TOOLS = frozenset({"Read", "Grep", "Glob", "LS", "ListDir"})

DANGEROUS_PATTERNS: dict[str, list[str]] = {
    "Bash": [r"\brm\s", r"\bsudo\b", r"\bcurl\b.*\|\s*bash"],
    "Write": [r"/etc/", r"/system/"],
}


def assess_risk(
    tool_name: str,
    input_data: dict[str, Any],
    workspace: str | None = None,
) -> Literal["safe", "dangerous", "forbidden"]:
    if workspace and _is_path_escape(input_data, workspace):
        return "forbidden"

    if tool_name in SAFE_TOOLS:
        return "safe"

    if tool_name in DANGEROUS_PATTERNS:
        input_str = str(input_data)
        for pattern in DANGEROUS_PATTERNS[tool_name]:
            if re.search(pattern, input_str):
                return "dangerous"

    return "safe"


def _is_path_escape(input_data: dict[str, Any], workspace: str) -> bool:
    for key in ("path", "file_path", "directory"):
        if key in input_data:
            resolved = os.path.realpath(str(input_data[key]))
            ws_resolved = os.path.realpath(workspace)
            if not resolved.startswith(ws_resolved):
                return True
    return False
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_risk.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/chatcc/approval/ tests/test_risk.py
git commit -m "feat: add risk assessment for tool permission checking"
```

---

### Task 15: ApprovalTable

**Files:**
- Create: `src/chatcc/approval/table.py`
- Create: `tests/test_approval.py`

- [ ] **Step 1: 写审批表测试**

`tests/test_approval.py`:
```python
import pytest
import asyncio
from chatcc.approval.table import ApprovalTable


@pytest.mark.asyncio
async def test_request_and_approve():
    table = ApprovalTable()
    future = table.request_approval(
        project="myapp",
        tool_name="Bash",
        input_summary="rm -rf dist/",
    )
    assert table.pending_count == 1

    table.approve(1)
    result = await asyncio.wait_for(future, timeout=1.0)
    assert result is True
    assert table.pending_count == 0


@pytest.mark.asyncio
async def test_request_and_deny():
    table = ApprovalTable()
    future = table.request_approval(
        project="myapp",
        tool_name="Bash",
        input_summary="sudo rm /",
    )
    table.deny(1)
    result = await asyncio.wait_for(future, timeout=1.0)
    assert result is False


@pytest.mark.asyncio
async def test_approve_oldest():
    table = ApprovalTable()
    f1 = table.request_approval("proj-a", "Bash", "cmd1")
    f2 = table.request_approval("proj-b", "Bash", "cmd2")
    assert table.pending_count == 2

    table.approve_oldest()
    r1 = await asyncio.wait_for(f1, timeout=1.0)
    assert r1 is True
    assert table.pending_count == 1


@pytest.mark.asyncio
async def test_approve_all():
    table = ApprovalTable()
    f1 = table.request_approval("a", "Bash", "c1")
    f2 = table.request_approval("b", "Bash", "c2")
    table.approve_all()
    assert await asyncio.wait_for(f1, timeout=1.0) is True
    assert await asyncio.wait_for(f2, timeout=1.0) is True
    assert table.pending_count == 0


def test_list_pending():
    table = ApprovalTable()
    table.request_approval("proj", "Bash", "rm -rf /")
    pending = table.list_pending()
    assert len(pending) == 1
    assert pending[0].project == "proj"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_approval.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 ApprovalTable**

`src/chatcc/approval/table.py`:
```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class PendingApproval:
    id: int
    project: str
    tool_name: str
    input_summary: str
    future: asyncio.Future
    created_at: datetime = field(default_factory=datetime.now)


class ApprovalTable:
    def __init__(self):
        self._pending: dict[int, PendingApproval] = {}
        self._next_id = 1

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def request_approval(
        self,
        project: str,
        tool_name: str,
        input_summary: str,
    ) -> asyncio.Future[bool]:
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        entry = PendingApproval(
            id=self._next_id,
            project=project,
            tool_name=tool_name,
            input_summary=input_summary,
            future=future,
        )
        self._pending[self._next_id] = entry
        self._next_id += 1
        return future

    def approve(self, approval_id: int) -> bool:
        entry = self._pending.pop(approval_id, None)
        if entry and not entry.future.done():
            entry.future.set_result(True)
            return True
        return False

    def deny(self, approval_id: int) -> bool:
        entry = self._pending.pop(approval_id, None)
        if entry and not entry.future.done():
            entry.future.set_result(False)
            return True
        return False

    def approve_oldest(self) -> bool:
        if not self._pending:
            return False
        oldest_id = min(self._pending.keys())
        return self.approve(oldest_id)

    def deny_oldest(self) -> bool:
        if not self._pending:
            return False
        oldest_id = min(self._pending.keys())
        return self.deny(oldest_id)

    def approve_all(self) -> int:
        count = 0
        for entry_id in list(self._pending.keys()):
            if self.approve(entry_id):
                count += 1
        return count

    def deny_all(self) -> int:
        count = 0
        for entry_id in list(self._pending.keys()):
            if self.deny(entry_id):
                count += 1
        return count

    def list_pending(self) -> list[PendingApproval]:
        return sorted(self._pending.values(), key=lambda x: x.id)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_approval.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/chatcc/approval/table.py tests/test_approval.py
git commit -m "feat: add ApprovalTable for dangerous operation approval flow"
```

---

## Chunk 8: P1 — 项目管理

### Task 16: ProjectManager

**Files:**
- Create: `src/chatcc/project/manager.py`
- Create: `tests/test_project_manager.py`

- [ ] **Step 1: 写项目管理测试**

`tests/test_project_manager.py`:
```python
import pytest
from pathlib import Path
from chatcc.project.manager import ProjectManager


@pytest.fixture
def pm(tmp_path):
    return ProjectManager(data_dir=tmp_path / ".chatcc" / "projects")


def test_create_project(pm, tmp_path):
    proj_path = tmp_path / "myapp"
    proj_path.mkdir()
    project = pm.create_project("myapp", str(proj_path))
    assert project.name == "myapp"
    assert project.is_default is True  # 第一个项目自动默认


def test_first_project_is_default(pm, tmp_path):
    p1 = tmp_path / "proj1"
    p1.mkdir()
    proj1 = pm.create_project("proj1", str(p1))
    assert proj1.is_default is True

    p2 = tmp_path / "proj2"
    p2.mkdir()
    proj2 = pm.create_project("proj2", str(p2))
    assert proj2.is_default is False


def test_list_projects(pm, tmp_path):
    for name in ["a", "b", "c"]:
        p = tmp_path / name
        p.mkdir()
        pm.create_project(name, str(p))
    assert len(pm.list_projects()) == 3


def test_switch_default(pm, tmp_path):
    for name in ["a", "b"]:
        p = tmp_path / name
        p.mkdir()
        pm.create_project(name, str(p))

    pm.switch_default("b")
    assert pm.default_project.name == "b"


def test_duplicate_name_raises(pm, tmp_path):
    p = tmp_path / "dup"
    p.mkdir()
    pm.create_project("dup", str(p))
    with pytest.raises(ValueError, match="already exists"):
        pm.create_project("dup", str(p))


def test_delete_project(pm, tmp_path):
    p = tmp_path / "del"
    p.mkdir()
    pm.create_project("del", str(p))
    pm.delete_project("del")
    assert len(pm.list_projects()) == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_project_manager.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 ProjectManager**

`src/chatcc/project/manager.py`:
```python
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from chatcc.project.models import Project, ProjectConfig


class ProjectManager:
    def __init__(self, data_dir: Path | None = None):
        self._data_dir = data_dir or (Path.home() / ".chatcc" / "projects")
        self._projects: dict[str, Project] = {}
        self._load_all()

    @property
    def default_project(self) -> Project | None:
        for p in self._projects.values():
            if p.is_default:
                return p
        return None

    @property
    def active_count(self) -> int:
        return len(self._projects)

    def create_project(self, name: str, path: str) -> Project:
        if name in self._projects:
            raise ValueError(f"Project '{name}' already exists")

        is_default = len(self._projects) == 0
        project = Project(name=name, path=path, is_default=is_default)
        self._projects[name] = project
        self._save_project(project)
        return project

    def list_projects(self) -> list[Project]:
        return list(self._projects.values())

    def get_project(self, name: str) -> Project | None:
        return self._projects.get(name)

    def switch_default(self, name: str) -> Project:
        if name not in self._projects:
            raise ValueError(f"Project '{name}' not found")

        for p in self._projects.values():
            if p.is_default:
                p.is_default = False
                self._save_project(p)

        project = self._projects[name]
        project.is_default = True
        self._save_project(project)
        return project

    def delete_project(self, name: str) -> None:
        project = self._projects.pop(name, None)
        if not project:
            raise ValueError(f"Project '{name}' not found")

        proj_dir = self._data_dir / name
        if proj_dir.exists():
            import shutil
            shutil.rmtree(proj_dir)

        if project.is_default and self._projects:
            first = next(iter(self._projects.values()))
            first.is_default = True
            self._save_project(first)

    def _save_project(self, project: Project) -> None:
        proj_dir = self._data_dir / project.name
        proj_dir.mkdir(parents=True, exist_ok=True)

        data = {
            "name": project.name,
            "path": project.path,
            "created_at": project.created_at.isoformat(),
            "is_default": project.is_default,
            "claude_options": {
                "permission_mode": project.config.permission_mode,
                "setting_sources": project.config.setting_sources,
                "model": project.config.model,
            },
        }
        with open(proj_dir / "project.yaml", "w") as f:
            yaml.dump(data, f, allow_unicode=True)

    def _load_all(self) -> None:
        if not self._data_dir.exists():
            return

        for proj_dir in self._data_dir.iterdir():
            if not proj_dir.is_dir():
                continue
            config_file = proj_dir / "project.yaml"
            if not config_file.exists():
                continue
            try:
                with open(config_file) as f:
                    data = yaml.safe_load(f) or {}
                from datetime import datetime
                claude_opts = data.get("claude_options", {})
                project = Project(
                    name=data["name"],
                    path=data["path"],
                    created_at=datetime.fromisoformat(data.get("created_at", datetime.now().isoformat())),
                    is_default=data.get("is_default", False),
                    config=ProjectConfig(
                        permission_mode=claude_opts.get("permission_mode", "acceptEdits"),
                        setting_sources=claude_opts.get("setting_sources", ["project"]),
                        model=claude_opts.get("model"),
                    ),
                )
                self._projects[project.name] = project
            except Exception:
                continue
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_project_manager.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/chatcc/project/manager.py tests/test_project_manager.py
git commit -m "feat: add ProjectManager with YAML persistence"
```

---

## Chunk 9: P1 — 会话历史

### Task 17: 会话历史 (JSONL)

**Files:**
- Create: `src/chatcc/memory/__init__.py`
- Create: `src/chatcc/memory/history.py`
- Create: `tests/test_history.py`

- [ ] **Step 1: 写会话历史测试**

`tests/test_history.py`:
```python
import pytest
from pathlib import Path
from chatcc.memory.history import ConversationHistory


@pytest.fixture
def history(tmp_path):
    return ConversationHistory(storage_dir=tmp_path)


def test_add_and_get_messages(history):
    history.add_message("user", "你好")
    history.add_message("assistant", "你好！有什么可以帮你的？")
    messages = history.get_messages()
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"


def test_message_count(history):
    for i in range(10):
        history.add_message("user", f"msg {i}")
    assert history.message_count == 10


def test_get_recent_messages(history):
    for i in range(20):
        history.add_message("user", f"msg {i}")
    recent = history.get_messages(limit=5)
    assert len(recent) == 5
    assert recent[-1]["content"] == "msg 19"


def test_persistence(tmp_path):
    h1 = ConversationHistory(storage_dir=tmp_path)
    h1.add_message("user", "persisted")
    h1.flush()

    h2 = ConversationHistory(storage_dir=tmp_path)
    messages = h2.get_messages()
    assert len(messages) == 1
    assert messages[0]["content"] == "persisted"


def test_truncate(history):
    for i in range(50):
        history.add_message("user", f"msg {i}")
    history.truncate(keep_recent=10)
    assert history.message_count == 10
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_history.py -v`
Expected: FAIL

- [ ] **Step 3: 实现会话历史**

`src/chatcc/memory/__init__.py`: 空文件

`src/chatcc/memory/history.py`:
```python
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class ConversationHistory:
    def __init__(self, storage_dir: Path):
        self._storage_dir = storage_dir
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._file = self._storage_dir / "history.jsonl"
        self._messages: list[dict[str, Any]] = []
        self._load()

    @property
    def message_count(self) -> int:
        return len(self._messages)

    def add_message(self, role: str, content: str) -> None:
        entry = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }
        self._messages.append(entry)
        self._append_to_file(entry)

    def get_messages(self, limit: int | None = None) -> list[dict[str, Any]]:
        if limit is None:
            return list(self._messages)
        return list(self._messages[-limit:])

    def truncate(self, keep_recent: int = 10) -> list[dict[str, Any]]:
        removed = self._messages[:-keep_recent] if keep_recent < len(self._messages) else []
        self._messages = self._messages[-keep_recent:]
        self._rewrite_file()
        return removed

    def flush(self) -> None:
        self._rewrite_file()

    def _append_to_file(self, entry: dict) -> None:
        with open(self._file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _rewrite_file(self) -> None:
        with open(self._file, "w", encoding="utf-8") as f:
            for entry in self._messages:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _load(self) -> None:
        if not self._file.exists():
            return
        with open(self._file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        self._messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_history.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/chatcc/memory/ tests/test_history.py
git commit -m "feat: add JSONL-based conversation history with truncation"
```

---

## Chunk 10: P2 — Telegram 渠道

### Task 18: Telegram 渠道实现

**Files:**
- Create: `src/chatcc/channel/telegram.py`
- Create: `tests/test_channel_telegram.py`

依赖: `python-telegram-bot` v21+ (已在 pyproject.toml 中声明)

**关键设计决策:**
- 使用手动 `initialize()` / `start()` / `start_polling()` 集成到项目的 asyncio 事件循环，不使用阻塞的 `run_polling()`
- 消息长度限制 4096 字符，内部自动拆分
- InlineKeyboard 支持按钮交互 (ActionGroup → InlineKeyboardButton)
- CallbackQuery 回调自动转为 InboundMessage 进入消息处理流程
- MarkdownV2 格式渲染代码块
- `allowed_users` 白名单验证

- [ ] **Step 1: 写 Telegram 渠道测试**

`tests/test_channel_telegram.py`:
```python
import pytest
from chatcc.channel.telegram import TelegramChannel
from chatcc.channel.message import (
    RichMessage,
    TextElement,
    CodeElement,
    ActionGroup,
    ActionButton,
    ProgressElement,
    DividerElement,
)


@pytest.fixture
def channel():
    config = {
        "token": "test-token-not-real",
        "allowed_users": ["123456"],
    }
    return TelegramChannel(config)


def test_not_authenticated_without_token():
    ch = TelegramChannel({})
    assert ch.is_authenticated() is False


def test_authenticated_with_token(channel):
    assert channel.is_authenticated() is True


def test_render_text_only(channel):
    rich = RichMessage(elements=[TextElement(content="Hello")])
    text, keyboard = channel.render(rich)
    assert "Hello" in text
    assert keyboard is None


def test_render_with_project_tag(channel):
    rich = RichMessage(
        elements=[TextElement(content="test")],
        project_tag="myapp",
    )
    text, _ = channel.render(rich)
    assert "[myapp]" in text


def test_render_code_block(channel):
    rich = RichMessage(elements=[
        CodeElement(code="print('hello')", language="python"),
    ])
    text, _ = channel.render(rich)
    assert "print('hello')" in text


def test_render_action_buttons(channel):
    rich = RichMessage(elements=[
        ActionGroup(buttons=[
            ActionButton(label="允许", command="/y 1"),
            ActionButton(label="拒绝", command="/n 1"),
        ]),
    ])
    text, keyboard = channel.render(rich)
    assert keyboard is not None


def test_render_full_approval_message(channel):
    rich = RichMessage(
        project_tag="myapp",
        elements=[
            TextElement(content="Claude Code 请求执行危险操作:"),
            CodeElement(code="rm -rf dist/", language="bash"),
            TextElement(content="工具: Bash | 请求 ID: #3"),
            DividerElement(),
            ActionGroup(buttons=[
                ActionButton(label="✅ 允许", command="/y 3"),
                ActionButton(label="❌ 拒绝", command="/n 3"),
            ]),
        ],
    )
    text, keyboard = channel.render(rich)
    assert "[myapp]" in text
    assert "rm -rf dist/" in text
    assert keyboard is not None


def test_split_long_message(channel):
    chunks = channel._split_text("a" * 5000, max_len=4096)
    assert len(chunks) == 2
    assert len(chunks[0]) <= 4096


def test_is_user_allowed(channel):
    assert channel._is_user_allowed("123456") is True
    assert channel._is_user_allowed("999999") is False


def test_empty_allowed_users_allows_all():
    ch = TelegramChannel({"token": "test", "allowed_users": []})
    assert ch._is_user_allowed("anyone") is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_channel_telegram.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 Telegram 渠道**

`src/chatcc/channel/telegram.py`:
```python
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from telegram import (
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from chatcc.channel.base import MessageChannel
from chatcc.channel.message import (
    ActionGroup,
    CodeElement,
    DividerElement,
    InboundMessage,
    OutboundMessage,
    ProgressElement,
    RichMessage,
    TextElement,
)

logger = logging.getLogger("chatcc.channel.telegram")


class TelegramChannel(MessageChannel):
    MAX_MESSAGE_LENGTH = 4096

    def __init__(self, config: dict[str, Any]):
        self._config = config
        self._token: str = config.get("token", "")
        self._allowed_users: list[str] = config.get("allowed_users", [])
        self._callback: Callable[[InboundMessage], Awaitable[None]] | None = None
        self._app: Application | None = None
        self._bot: Bot | None = None

    async def start(self) -> None:
        if not self._token:
            raise RuntimeError("Telegram token not configured")

        self._app = (
            ApplicationBuilder()
            .token(self._token)
            .build()
        )
        self._bot = self._app.bot

        self._app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self._handle_text_message,
        ))
        self._app.add_handler(MessageHandler(
            filters.COMMAND,
            self._handle_command_message,
        ))
        self._app.add_handler(CallbackQueryHandler(self._handle_callback))

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()
        logger.info("Telegram channel started")

    async def stop(self) -> None:
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
        logger.info("Telegram channel stopped")

    async def send(self, message: OutboundMessage) -> None:
        if not self._bot:
            raise RuntimeError("Telegram bot not started")

        if isinstance(message.content, RichMessage):
            text, keyboard = self.render(message.content)
            for chunk in self._split_text(text, self.MAX_MESSAGE_LENGTH):
                await self._bot.send_message(
                    chat_id=message.chat_id,
                    text=chunk,
                    reply_markup=keyboard if chunk == self._split_text(text, self.MAX_MESSAGE_LENGTH)[-1] else None,
                    parse_mode="Markdown",
                    reply_to_message_id=message.reply_to,
                )
        else:
            for chunk in self._split_text(str(message.content), self.MAX_MESSAGE_LENGTH):
                await self._bot.send_message(
                    chat_id=message.chat_id,
                    text=chunk,
                    reply_to_message_id=message.reply_to,
                )

    def render(self, message: RichMessage) -> tuple[str, InlineKeyboardMarkup | None]:
        text_parts: list[str] = []
        keyboard_rows: list[list[InlineKeyboardButton]] = []

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
                    keyboard_rows.append(row)
                case ProgressElement(description=desc, project=proj):
                    tag = f"[{proj}] " if proj else ""
                    text_parts.append(f"⏳ {tag}{desc}")
                case DividerElement():
                    text_parts.append("───────────")

        text = "\n\n".join(text_parts)
        keyboard = InlineKeyboardMarkup(keyboard_rows) if keyboard_rows else None
        return text, keyboard

    def on_message(self, callback: Callable[[InboundMessage], Awaitable[None]]) -> None:
        self._callback = callback

    def is_authenticated(self) -> bool:
        return bool(self._token)

    def _is_user_allowed(self, user_id: str) -> bool:
        if not self._allowed_users:
            return True
        return user_id in self._allowed_users

    @staticmethod
    def _split_text(text: str, max_len: int) -> list[str]:
        if len(text) <= max_len:
            return [text]
        chunks = []
        while text:
            if len(text) <= max_len:
                chunks.append(text)
                break
            split_at = text.rfind("\n", 0, max_len)
            if split_at == -1:
                split_at = max_len
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip("\n")
        return chunks

    async def _handle_text_message(self, update: Update, context: Any) -> None:
        if not update.message or not update.message.text:
            return
        user_id = str(update.message.from_user.id)
        if not self._is_user_allowed(user_id):
            return

        if self._callback:
            msg = InboundMessage(
                sender_id=user_id,
                content=update.message.text,
                chat_id=str(update.message.chat_id),
                raw=update,
            )
            await self._callback(msg)

    async def _handle_command_message(self, update: Update, context: Any) -> None:
        if not update.message or not update.message.text:
            return
        user_id = str(update.message.from_user.id)
        if not self._is_user_allowed(user_id):
            return

        if self._callback:
            msg = InboundMessage(
                sender_id=user_id,
                content=update.message.text,
                chat_id=str(update.message.chat_id),
                raw=update,
            )
            await self._callback(msg)

    async def _handle_callback(self, update: Update, context: Any) -> None:
        query = update.callback_query
        if not query or not query.data:
            return

        await query.answer()

        user_id = str(query.from_user.id)
        if not self._is_user_allowed(user_id):
            return

        if self._callback:
            msg = InboundMessage(
                sender_id=user_id,
                content=query.data,
                chat_id=str(query.message.chat_id),
                raw=update,
            )
            await self._callback(msg)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_channel_telegram.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/chatcc/channel/telegram.py tests/test_channel_telegram.py
git commit -m "feat: add Telegram channel with InlineKeyboard and callback support"
```

---

## Chunk 11: P2 — 飞书渠道

### Task 19: 飞书渠道实现

**Files:**
- Create: `src/chatcc/channel/feishu.py`
- Create: `tests/test_channel_feishu.py`

依赖: `lark-oapi` v1.5+ (已在 pyproject.toml 中声明)

**关键设计决策:**
- 使用 WebSocket 长连接 (`lark.ws.Client`) 接收消息，无需公网 IP
- 发送消息使用 `client.im.v1.message.acreate` 异步接口
- 富消息渲染为 Interactive Card (支持按钮回调)
- 简单消息渲染为 Post (富文本) 格式
- 需要配置 `app_id` 和 `app_secret`
- 需要开通权限: `im:message:send_as_bot`, `im:message:receive`
- `allowed_users` 白名单 (使用 open_id)
- 按钮回调通过 card action callback 处理，转为 InboundMessage

- [ ] **Step 1: 写飞书渠道测试**

`tests/test_channel_feishu.py`:
```python
import pytest
from chatcc.channel.feishu import FeishuChannel
from chatcc.channel.message import (
    RichMessage,
    TextElement,
    CodeElement,
    ActionGroup,
    ActionButton,
    ProgressElement,
    DividerElement,
)


@pytest.fixture
def channel():
    config = {
        "app_id": "test-app-id",
        "app_secret": "test-app-secret",
        "allowed_users": [],
    }
    return FeishuChannel(config)


def test_not_authenticated_without_credentials():
    ch = FeishuChannel({})
    assert ch.is_authenticated() is False


def test_authenticated_with_credentials(channel):
    assert channel.is_authenticated() is True


def test_render_text_only(channel):
    rich = RichMessage(elements=[TextElement(content="Hello")])
    card = channel.render(rich)
    assert isinstance(card, dict)
    assert card["msg_type"] == "interactive"
    card_body = card["card"]
    assert "elements" in card_body


def test_render_with_project_tag(channel):
    rich = RichMessage(
        elements=[TextElement(content="test")],
        project_tag="myapp",
    )
    card = channel.render(rich)
    header = card["card"]["header"]
    assert "myapp" in header["title"]["content"]


def test_render_code_block(channel):
    rich = RichMessage(elements=[
        CodeElement(code="print('hello')", language="python"),
    ])
    card = channel.render(rich)
    elements = card["card"]["elements"]
    code_found = False
    for el in elements:
        if el.get("tag") == "div":
            text_content = el.get("text", {}).get("content", "")
            if "print('hello')" in text_content:
                code_found = True
    assert code_found


def test_render_action_buttons(channel):
    rich = RichMessage(elements=[
        ActionGroup(buttons=[
            ActionButton(label="允许", command="/y 1"),
            ActionButton(label="拒绝", command="/n 1"),
        ]),
    ])
    card = channel.render(rich)
    elements = card["card"]["elements"]
    action_found = any(el.get("tag") == "action" for el in elements)
    assert action_found


def test_render_full_approval_message(channel):
    rich = RichMessage(
        project_tag="myapp",
        elements=[
            TextElement(content="Claude Code 请求执行危险操作:"),
            CodeElement(code="rm -rf dist/", language="bash"),
            TextElement(content="工具: Bash | 请求 ID: #3"),
            DividerElement(),
            ActionGroup(buttons=[
                ActionButton(label="✅ 允许", command="/y 3"),
                ActionButton(label="❌ 拒绝", command="/n 3"),
            ]),
        ],
    )
    card = channel.render(rich)
    assert card["msg_type"] == "interactive"
    assert "myapp" in card["card"]["header"]["title"]["content"]


def test_render_progress(channel):
    rich = RichMessage(elements=[
        ProgressElement(description="正在执行...", project="myapp"),
    ])
    card = channel.render(rich)
    elements = card["card"]["elements"]
    assert any(
        "正在执行" in str(el)
        for el in elements
    )


def test_build_text_message(channel):
    """简单文本直接发 text 类型"""
    payload = channel._build_send_payload("chat_123", "hello")
    assert payload["receive_id"] == "chat_123"
    assert payload["msg_type"] == "text"


def test_build_rich_message(channel):
    """RichMessage 发 interactive card"""
    rich = RichMessage(elements=[TextElement(content="test")])
    payload = channel._build_send_payload("chat_123", rich)
    assert payload["msg_type"] == "interactive"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_channel_feishu.py -v`
Expected: FAIL

- [ ] **Step 3: 实现飞书渠道**

`src/chatcc/channel/feishu.py`:
```python
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
)

from chatcc.channel.base import MessageChannel
from chatcc.channel.message import (
    ActionGroup,
    CodeElement,
    DividerElement,
    InboundMessage,
    OutboundMessage,
    ProgressElement,
    RichMessage,
    TextElement,
)

logger = logging.getLogger("chatcc.channel.feishu")


class FeishuChannel(MessageChannel):

    def __init__(self, config: dict[str, Any]):
        self._config = config
        self._app_id: str = config.get("app_id", "")
        self._app_secret: str = config.get("app_secret", "")
        self._allowed_users: list[str] = config.get("allowed_users", [])
        self._callback: Callable[[InboundMessage], Awaitable[None]] | None = None
        self._api_client: lark.Client | None = None
        self._ws_client: lark.ws.Client | None = None

    async def start(self) -> None:
        if not self._app_id or not self._app_secret:
            raise RuntimeError("Feishu app_id/app_secret not configured")

        self._api_client = (
            lark.Client.builder()
            .app_id(self._app_id)
            .app_secret(self._app_secret)
            .build()
        )

        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_message_event)
            .build()
        )

        card_handler = (
            lark.CardActionHandler.builder("")
            .register(self._on_card_action)
            .build()
        )

        self._ws_client = lark.ws.Client(
            self._app_id,
            self._app_secret,
            event_handler=event_handler,
            card_handler=card_handler,
            log_level=lark.LogLevel.INFO,
        )

        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, self._ws_client.start)
        logger.info("Feishu channel started (WebSocket)")

    async def stop(self) -> None:
        logger.info("Feishu channel stopped")

    async def send(self, message: OutboundMessage) -> None:
        if not self._api_client:
            raise RuntimeError("Feishu API client not initialized")

        payload = self._build_send_payload(message.chat_id, message.content)

        request = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(payload["receive_id"])
                .msg_type(payload["msg_type"])
                .content(json.dumps(payload["content"], ensure_ascii=False))
                .build()
            )
            .build()
        )

        response = await self._api_client.im.v1.message.acreate(request)
        if not response.success():
            logger.error(f"Failed to send message: {response.code} - {response.msg}")

    def render(self, message: RichMessage) -> dict[str, Any]:
        elements: list[dict[str, Any]] = []

        for el in message.elements:
            match el:
                case TextElement(content=content):
                    elements.append({
                        "tag": "div",
                        "text": {
                            "content": content,
                            "tag": "lark_md",
                        },
                    })
                case CodeElement(code=code, language=lang):
                    md_code = f"```{lang}\n{code}\n```"
                    elements.append({
                        "tag": "div",
                        "text": {
                            "content": md_code,
                            "tag": "lark_md",
                        },
                    })
                case ActionGroup(buttons=buttons):
                    actions = []
                    for b in buttons:
                        actions.append({
                            "tag": "button",
                            "text": {
                                "content": b.label,
                                "tag": "lark_md",
                            },
                            "type": "primary" if "/y" in b.command else "danger",
                            "value": {"command": b.command},
                        })
                    elements.append({
                        "tag": "action",
                        "actions": actions,
                    })
                case ProgressElement(description=desc, project=proj):
                    tag = f"[{proj}] " if proj else ""
                    elements.append({
                        "tag": "note",
                        "elements": [{
                            "tag": "plain_text",
                            "content": f"⏳ {tag}{desc}",
                        }],
                    })
                case DividerElement():
                    elements.append({"tag": "hr"})

        header = {}
        if message.project_tag:
            header = {
                "title": {
                    "content": f"[{message.project_tag}] ChatCC",
                    "tag": "plain_text",
                },
            }
        else:
            header = {
                "title": {
                    "content": "ChatCC",
                    "tag": "plain_text",
                },
            }

        return {
            "msg_type": "interactive",
            "card": {
                "header": header,
                "elements": elements,
            },
        }

    def on_message(self, callback: Callable[[InboundMessage], Awaitable[None]]) -> None:
        self._callback = callback

    def is_authenticated(self) -> bool:
        return bool(self._app_id and self._app_secret)

    def _build_send_payload(
        self,
        chat_id: str,
        content: str | RichMessage,
    ) -> dict[str, Any]:
        if isinstance(content, RichMessage):
            card_data = self.render(content)
            return {
                "receive_id": chat_id,
                "msg_type": "interactive",
                "content": card_data["card"],
            }
        return {
            "receive_id": chat_id,
            "msg_type": "text",
            "content": {"text": content},
        }

    def _is_user_allowed(self, open_id: str) -> bool:
        if not self._allowed_users:
            return True
        return open_id in self._allowed_users

    def _on_message_event(self, data: Any) -> None:
        try:
            event = data.event
            sender = event.sender.sender_id.open_id
            message = event.message

            if not self._is_user_allowed(sender):
                return

            content_json = json.loads(message.content)
            text = content_json.get("text", "")

            if self._callback:
                msg = InboundMessage(
                    sender_id=sender,
                    content=text,
                    chat_id=message.chat_id,
                    raw=data,
                )
                asyncio.get_event_loop().create_task(self._callback(msg))

        except Exception:
            logger.exception("Error handling Feishu message event")

    def _on_card_action(self, data: Any) -> Any:
        try:
            action = data.event.action
            value = action.value
            command = value.get("command", "")
            open_id = data.event.operator.open_id
            chat_id = data.event.context.open_chat_id

            if not command or not self._is_user_allowed(open_id):
                return None

            if self._callback:
                msg = InboundMessage(
                    sender_id=open_id,
                    content=command,
                    chat_id=chat_id,
                    raw=data,
                )
                asyncio.get_event_loop().create_task(self._callback(msg))

        except Exception:
            logger.exception("Error handling Feishu card action")
        return None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_channel_feishu.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 更新 config.yaml 示例和 architecture.md 中的渠道能力对比表**

在 `docs/architecture.md` 的渠道能力对比表中添加飞书:

| 能力 | Telegram | Discord | WeChat | 飞书 | CLI |
|------|----------|---------|--------|------|-----|
| Markdown | 部分支持 | 支持 | 不支持 | 支持 (lark_md) | 支持 |
| 按钮/快捷操作 | InlineKeyboard | Button | 不支持 | Interactive Card | 不支持 |
| 代码块 | 支持 | 支持 | 不支持 | 支持 | 支持 |
| 消息长度 | 4096 | 2000 | ~2000 | ~30000 | 无限 |
| 引用回复 | 支持 | 支持 | 支持 | 支持 | 不支持 |

- [ ] **Step 6: Commit**

```bash
git add src/chatcc/channel/feishu.py tests/test_channel_feishu.py
git commit -m "feat: add Feishu channel with WebSocket and Interactive Card support"
```

---

## Chunk 12: P2 — 费用追踪 + 长期记忆 (骨架)

### Task 20: 费用追踪

**Files:**
- Create: `src/chatcc/cost/__init__.py`
- Create: `src/chatcc/cost/tracker.py`
- Create: `tests/test_cost.py`

- [ ] **Step 1: 写费用追踪测试**

`tests/test_cost.py`:
```python
from chatcc.cost.tracker import CostTracker


def test_initial_cost_zero():
    tracker = CostTracker()
    assert tracker.total_cost == 0.0


def test_track_agent_cost():
    tracker = CostTracker()
    tracker.track_agent(0.001)
    tracker.track_agent(0.002)
    assert tracker.total_agent_cost == pytest.approx(0.003)


def test_track_claude_code_cost():
    tracker = CostTracker()
    tracker.track_claude_code(0.05)
    assert tracker.total_claude_code_cost == pytest.approx(0.05)


def test_budget_warning(capsys):
    tracker = CostTracker(budget_limit=1.0)
    tracker.track_claude_code(0.85)
    assert tracker.is_budget_warning is True


def test_no_warning_under_threshold():
    tracker = CostTracker(budget_limit=1.0)
    tracker.track_claude_code(0.5)
    assert tracker.is_budget_warning is False


import pytest
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_cost.py -v`
Expected: FAIL

- [ ] **Step 3: 实现费用追踪**

`src/chatcc/cost/__init__.py`: 空文件

`src/chatcc/cost/tracker.py`:
```python
from __future__ import annotations


class CostTracker:
    def __init__(self, budget_limit: float | None = None):
        self.total_agent_cost: float = 0.0
        self.total_claude_code_cost: float = 0.0
        self.budget_limit = budget_limit

    @property
    def total_cost(self) -> float:
        return self.total_agent_cost + self.total_claude_code_cost

    @property
    def is_budget_warning(self) -> bool:
        if not self.budget_limit:
            return False
        return self.total_cost > self.budget_limit * 0.8

    def track_agent(self, cost: float) -> None:
        self.total_agent_cost += cost

    def track_claude_code(self, cost: float) -> None:
        self.total_claude_code_cost += cost

    def summary(self) -> str:
        lines = [
            f"主 Agent 费用: ${self.total_agent_cost:.4f}",
            f"Claude Code 费用: ${self.total_claude_code_cost:.4f}",
            f"总费用: ${self.total_cost:.4f}",
        ]
        if self.budget_limit:
            lines.append(f"预算上限: ${self.budget_limit:.2f}")
            if self.is_budget_warning:
                lines.append("⚠️ 费用已超过预算 80%")
        return "\n".join(lines)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_cost.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/chatcc/cost/ tests/test_cost.py
git commit -m "feat: add cost tracker for agent and Claude Code expenses"
```

---

### Task 21: 长期记忆 (骨架)

**Files:**
- Create: `src/chatcc/memory/longterm.py`
- Create: `tests/test_longterm.py`

- [ ] **Step 1: 写长期记忆测试**

`tests/test_longterm.py`:
```python
import pytest
from pathlib import Path
from chatcc.memory.longterm import LongTermMemory


@pytest.fixture
def memory(tmp_path):
    return LongTermMemory(memory_dir=tmp_path / "memory")


def test_read_empty_memory(memory):
    content = memory.read_core()
    assert content == ""


def test_write_and_read_core(memory):
    memory.write_core("用户偏好: 中文回复")
    content = memory.read_core()
    assert "中文回复" in content


def test_append_daily_note(memory):
    memory.append_daily_note("今天完成了认证模块")
    notes = memory.get_recent_daily_notes(days=1)
    assert "认证模块" in notes[0]


def test_get_context(memory):
    memory.write_core("核心记忆")
    memory.append_daily_note("日志条目")
    context = memory.get_context()
    assert "核心记忆" in context
    assert "日志条目" in context
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_longterm.py -v`
Expected: FAIL

- [ ] **Step 3: 实现长期记忆**

`src/chatcc/memory/longterm.py`:
```python
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path


class LongTermMemory:
    def __init__(self, memory_dir: Path | None = None):
        self._dir = memory_dir or (Path.home() / ".chatcc" / "memory")
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def _core_file(self) -> Path:
        return self._dir / "MEMORY.md"

    def read_core(self) -> str:
        if not self._core_file.exists():
            return ""
        return self._core_file.read_text(encoding="utf-8")

    def write_core(self, content: str) -> None:
        self._core_file.write_text(content, encoding="utf-8")

    def append_daily_note(self, note: str) -> None:
        today = datetime.now()
        month_dir = self._dir / today.strftime("%Y%m")
        month_dir.mkdir(parents=True, exist_ok=True)

        daily_file = month_dir / f"{today.strftime('%Y%m%d')}.md"
        timestamp = today.strftime("%H:%M")

        with open(daily_file, "a", encoding="utf-8") as f:
            f.write(f"- [{timestamp}] {note}\n")

    def get_recent_daily_notes(self, days: int = 3) -> list[str]:
        notes = []
        for i in range(days):
            date = datetime.now() - timedelta(days=i)
            month_dir = self._dir / date.strftime("%Y%m")
            daily_file = month_dir / f"{date.strftime('%Y%m%d')}.md"
            if daily_file.exists():
                notes.append(daily_file.read_text(encoding="utf-8"))
        return notes

    def get_context(self, recent_days: int = 3) -> str:
        parts = []
        core = self.read_core()
        if core:
            parts.append(f"## 长期记忆\n{core}")

        daily_notes = self.get_recent_daily_notes(days=recent_days)
        if daily_notes:
            parts.append("## 近期笔记")
            for note in daily_notes:
                parts.append(note)

        return "\n\n".join(parts)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_longterm.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add src/chatcc/memory/longterm.py tests/test_longterm.py
git commit -m "feat: add long-term memory with MEMORY.md and daily notes"
```

---

## Chunk 13: 集成验证

### Task 22: 全量测试 + 集成验证

- [ ] **Step 1: 运行全量测试**

Run: `uv run pytest tests/ -v --tb=short`
Expected: 全部 PASS

- [ ] **Step 2: 类型检查 (可选)**

Run: `uv run ruff check src/chatcc/`
Expected: 无严重错误

- [ ] **Step 3: 验证项目结构完整性**

运行 `find src/chatcc -name "*.py" | sort` 确认目录结构与架构文档一致:

```
src/chatcc/__init__.py
src/chatcc/main.py
src/chatcc/app.py
src/chatcc/config.py
src/chatcc/channel/__init__.py
src/chatcc/channel/base.py
src/chatcc/channel/message.py
src/chatcc/channel/cli.py
src/chatcc/channel/telegram.py
src/chatcc/channel/feishu.py
src/chatcc/channel/factory.py
src/chatcc/router/__init__.py
src/chatcc/router/router.py
src/chatcc/agent/__init__.py
src/chatcc/agent/dispatcher.py
src/chatcc/agent/provider.py
src/chatcc/agent/prompt.py
src/chatcc/approval/__init__.py
src/chatcc/approval/risk.py
src/chatcc/approval/table.py
src/chatcc/project/__init__.py
src/chatcc/project/models.py
src/chatcc/project/manager.py
src/chatcc/claude/__init__.py
src/chatcc/claude/session.py
src/chatcc/memory/__init__.py
src/chatcc/memory/history.py
src/chatcc/memory/longterm.py
src/chatcc/cost/__init__.py
src/chatcc/cost/tracker.py
src/chatcc/personas/default.md
```

- [ ] **Step 4: 全量 Commit**

```bash
git add -A
git commit -m "feat: complete MVP implementation (P0+P1+P2 channels)"
```

---

## 配置参考

### Telegram 配置 (`~/.chatcc/config.yaml`)

```yaml
channel:
  type: telegram
  telegram:
    token: "${TELEGRAM_BOT_TOKEN}"
    allowed_users:
      - "123456789"
```

**获取 Token:**
1. 在 Telegram 中找到 @BotFather
2. 发送 `/newbot`，按提示创建 bot
3. 获得 bot token，设置环境变量 `TELEGRAM_BOT_TOKEN`

### 飞书配置 (`~/.chatcc/config.yaml`)

```yaml
channel:
  type: feishu
  feishu:
    app_id: "${FEISHU_APP_ID}"
    app_secret: "${FEISHU_APP_SECRET}"
    allowed_users: []  # 空列表允许所有用户
```

**获取凭证:**
1. 前往 [飞书开放平台](https://open.feishu.cn/) 创建企业自建应用
2. 在应用的「凭证与基础信息」中获取 App ID 和 App Secret
3. 在「权限管理」中开通:
   - `im:message:send_as_bot` (以机器人身份发送消息)
   - `im:message:receive` (接收消息)
4. 在「事件订阅」中:
   - 选择「使用长连接」方式
   - 添加 `im.message.receive_v1` 事件
5. 发布应用版本
6. 设置环境变量 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET`

---

## 后续阶段 (P3)

以下模块不在本次实现范围内，后续按需规划:

| 模块 | 说明 |
|------|------|
| 多项目并发 | 跨项目并行执行 |
| 服务管理 | 启动/停止/日志工具 |
| 工具安装 | skill/mcp 安装管理 |
| 消息渠道 (Discord) | Discord 渠道实现 |
| 会话摘要压缩 | 主 Agent 会话自动压缩 |
| Agent 工具集完善 | 项目管理工具、命令执行工具等注册到 pydantic-ai |
