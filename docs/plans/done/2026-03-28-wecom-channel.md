# 企业微信 (WeCom) 渠道接入实现计划

> **Status: ✅ COMPLETED** (2026-03-28)

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 接入企业微信"智能机器人"长连接模式作为新的 MessageChannel，支持消息收发、模板卡片交互按钮。

**Architecture:** 使用 `wecom-aibot-sdk` (PyPI) 提供的 WebSocket 长连接客户端，与飞书渠道同构 — 客户端主动连上 `wss://openws.work.weixin.qq.com`，无需公网 IP / HTTP 回调。接收文本消息和卡片按钮事件，发送时将 RichMessage 渲染为 Markdown 或 Template Card。

**Tech Stack:** Python 3.12, asyncio, `wecom-aibot-sdk` (WebSocket), 企微 Template Card JSON

**Reference files (实现时对照):**
- 飞书渠道 (最接近的同构参考): `src/chatcc/channel/feishu.py`
- Telegram 渠道 (更简洁的参考): `src/chatcc/channel/telegram.py`
- 基类: `src/chatcc/channel/base.py`
- 消息类型: `src/chatcc/channel/message.py`
- 工厂: `src/chatcc/channel/factory.py`
- 配置: `src/chatcc/config.py`

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `src/chatcc/channel/wecom.py` | WeComChannel 主体 — WSClient 生命周期、消息收发、Template Card 渲染 |
| Modify | `src/chatcc/channel/factory.py` | CHANNEL_REGISTRY + CHANNEL_LABELS 注册 wecom |
| Modify | `src/chatcc/config.py` | ChannelConfig 加 `wecom` 字段 + load_config 解析 |
| Modify | `pyproject.toml` | 添加 `wecom-aibot-sdk` 依赖 |
| Create | `tests/test_channel_wecom.py` | WeComChannel 单元测试 |
| Modify | `tests/test_channel_factory.py` | 加 wecom 工厂测试 |
| Modify | `tests/test_channel_setup.py` | 加 wecom interactive_setup 测试 |

---

## wecom-aibot-sdk 关键 API 备忘

```python
from wecom_aibot_sdk import WSClient, generate_req_id

# 创建客户端
ws_client = WSClient(bot_id="...", secret="...")

# 事件监听
ws_client.on("message.text", async_handler)       # frame: dict
ws_client.on("message.image", async_handler)
ws_client.on("event.template_card_event", async_handler)  # 按钮点击
ws_client.on("event.enter_chat", async_handler)

# 连接管理
await ws_client.connect()
await ws_client.disconnect()

# 发送消息 (主动推送，不依赖 frame)
await ws_client.send_message("chatid", {
    "msgtype": "markdown",
    "markdown": {"content": "**hello**"},
})

await ws_client.send_message("chatid", {
    "msgtype": "template_card",
    "template_card": { ... },
})

# 被动回复 (需要 frame)
await ws_client.reply(frame, {"msgtype": "markdown", ...})
await ws_client.reply_template_card(frame, template_card_dict)

# 更新卡片 (按钮点击后更新原卡片)
await ws_client.update_template_card(frame, new_card_dict)
```

### 消息帧结构

```python
# message.text 帧
frame = {
    "header": {"event_type": "message"},
    "body": {
        "msg_id": "xxx",
        "chat_id": "wrkSFfCgAAxxxxxx",
        "chat_type": "single",  # or "group"
        "from": {"user_id": "zhangsan", "name": "张三"},
        "text": {"content": "你好"},
    }
}

# event.template_card_event 帧
frame = {
    "header": {"event_type": "template_card_event"},
    "body": {
        "event_key": "/y 3",          # 对应 button key
        "task_id": "task_xxx",
        "from": {"user_id": "zhangsan"},
        "chat_id": "wrkSFfCgAAxxxxxx",
    }
}
```

---

## Chunk 1: WeComChannel 核心实现 + 注册

### Task 1: 添加依赖 + 配置支持

**Files:**
- Modify: `pyproject.toml:6-19`
- Modify: `src/chatcc/config.py:36-41` (ChannelConfig)
- Modify: `src/chatcc/config.py:126-134` (load_config channel parsing)
- Test: `tests/test_config.py`

- [x] **Step 1: 在 pyproject.toml 添加 wecom-aibot-sdk 依赖**

```toml
# pyproject.toml dependencies 列表末尾追加:
    "wecom-aibot-sdk",
```

- [x] **Step 2: 在 ChannelConfig 加 wecom 字段**

```python
# src/chatcc/config.py — ChannelConfig dataclass
@dataclass
class ChannelConfig:
    type: str = "cli"
    telegram: dict[str, Any] = field(default_factory=dict)
    feishu: dict[str, Any] = field(default_factory=dict)
    wechat: dict[str, Any] = field(default_factory=dict)
    wecom: dict[str, Any] = field(default_factory=dict)     # ← 新增
    discord: dict[str, Any] = field(default_factory=dict)
```

- [x] **Step 3: 在 load_config 解析 wecom 配置**

```python
# src/chatcc/config.py — load_config 的 channel 解析部分
    if "channel" in expanded:
        ch = expanded["channel"]
        config.channel = ChannelConfig(
            type=ch.get("type", "cli"),
            telegram=ch.get("telegram", {}),
            feishu=ch.get("feishu", {}),
            wechat=ch.get("wechat", {}),
            wecom=ch.get("wecom", {}),       # ← 新增
            discord=ch.get("discord", {}),
        )
```

- [x] **Step 4: 运行现有 config 测试确认不破坏**

Run: `pytest tests/test_config.py -v`
Expected: 全部 PASS

- [x] **Step 5: Commit**

```bash
git add pyproject.toml src/chatcc/config.py
git commit -m "feat(config): add wecom channel config support"
```

---

### Task 2: 注册 WeComChannel 到工厂

**Files:**
- Modify: `src/chatcc/channel/factory.py:9-21`
- Test: `tests/test_channel_factory.py`

- [x] **Step 1: 写 factory 测试**

```python
# tests/test_channel_factory.py — 追加

def test_get_channel_class_wecom():
    from chatcc.channel.wecom import WeComChannel

    assert get_channel_class("wecom") is WeComChannel
```

- [x] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_channel_factory.py::test_get_channel_class_wecom -v`
Expected: FAIL (ModuleNotFoundError)

- [x] **Step 3: 在 factory.py 注册 wecom**

```python
# src/chatcc/channel/factory.py

CHANNEL_REGISTRY: dict[str, tuple[str, str]] = {
    "cli": ("chatcc.channel.cli", "CliChannel"),
    "telegram": ("chatcc.channel.telegram", "TelegramChannel"),
    "feishu": ("chatcc.channel.feishu", "FeishuChannel"),
    "wechat": ("chatcc.channel.wechatbot", "WeChatChannel"),
    "wecom": ("chatcc.channel.wecom", "WeComChannel"),       # ← 新增
}

CHANNEL_LABELS: list[tuple[str, str]] = [
    ("telegram", "Telegram"),
    ("feishu", "飞书 (Feishu)"),
    ("wechat", "微信 (WeChat)"),
    ("wecom", "企业微信 (WeCom)"),                             # ← 新增
    ("cli", "CLI (终端调试)"),
]
```

注意: 此时测试仍会失败 (wecom 模块还不存在)，Task 3 创建模块后才能通过。

---

### Task 3: 实现 WeComChannel 主体

**Files:**
- Create: `src/chatcc/channel/wecom.py`
- Test: `tests/test_channel_wecom.py`

以下是完整的 `wecom.py` 实现，按照飞书渠道的同构模式。

- [x] **Step 1: 写测试文件 — 认证和配置**

```python
# tests/test_channel_wecom.py

import pytest
from chatcc.channel.wecom import WeComChannel
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
        "bot_id": "test-bot-id",
        "secret": "test-bot-secret",
        "allowed_users": [],
    }
    return WeComChannel(config)


def test_not_authenticated_without_credentials():
    ch = WeComChannel({})
    assert ch.is_authenticated() is False


def test_authenticated_with_credentials(channel):
    assert channel.is_authenticated() is True


def test_user_allowed_empty_list(channel):
    assert channel._is_user_allowed("anyone") is True


def test_user_allowed_restricted():
    ch = WeComChannel({
        "bot_id": "id",
        "secret": "secret",
        "allowed_users": ["zhangsan"],
    })
    assert ch._is_user_allowed("zhangsan") is True
    assert ch._is_user_allowed("lisi") is False
```

- [x] **Step 2: 写测试 — render() 纯文本**

```python
# tests/test_channel_wecom.py — 追加

def test_render_text_only(channel):
    rich = RichMessage(elements=[TextElement(content="Hello")])
    result = channel.render(rich)
    assert result["msgtype"] == "markdown"
    assert "Hello" in result["markdown"]["content"]


def test_render_with_project_tag(channel):
    rich = RichMessage(
        elements=[TextElement(content="test")],
        project_tag="myapp",
    )
    result = channel.render(rich)
    assert "[myapp]" in result["markdown"]["content"]


def test_render_code_block(channel):
    rich = RichMessage(
        elements=[CodeElement(code="print('hello')", language="python")]
    )
    result = channel.render(rich)
    assert "print('hello')" in result["markdown"]["content"]


def test_render_progress(channel):
    rich = RichMessage(
        elements=[ProgressElement(description="正在执行...", project="myapp")]
    )
    result = channel.render(rich)
    assert "正在执行" in result["markdown"]["content"]


def test_render_divider(channel):
    rich = RichMessage(
        elements=[TextElement(content="above"), DividerElement(), TextElement(content="below")]
    )
    result = channel.render(rich)
    content = result["markdown"]["content"]
    assert "above" in content
    assert "below" in content
```

- [x] **Step 3: 写测试 — render() 带按钮时返回 template_card**

```python
# tests/test_channel_wecom.py — 追加

def test_render_action_buttons(channel):
    rich = RichMessage(
        elements=[
            TextElement(content="⚠️ 危险操作"),
            ActionGroup(
                buttons=[
                    ActionButton(label="✅ 确认", command="/y 1"),
                    ActionButton(label="❌ 拒绝", command="/n 1"),
                ]
            ),
        ]
    )
    result = channel.render(rich)
    assert result["msgtype"] == "template_card"
    card = result["template_card"]
    assert card["card_type"] == "button_interaction"
    assert len(card["button_list"]) == 2
    assert card["button_list"][0]["text"] == "✅ 确认"
    assert card["button_list"][0]["key"] == "/y 1"


def test_render_full_approval_message(channel):
    rich = RichMessage(
        project_tag="myapp",
        elements=[
            TextElement(content="Claude Code 请求执行危险操作:"),
            CodeElement(code="rm -rf dist/", language="bash"),
            DividerElement(),
            ActionGroup(
                buttons=[
                    ActionButton(label="✅ 允许", command="/y 3"),
                    ActionButton(label="❌ 拒绝", command="/n 3"),
                ]
            ),
        ],
    )
    result = channel.render(rich)
    assert result["msgtype"] == "template_card"
    card = result["template_card"]
    assert "[myapp]" in card["main_title"]["title"]
    assert len(card["button_list"]) == 2
    # 文本内容应在 sub_title_text 中
    assert "rm -rf dist/" in card["sub_title_text"]
```

- [x] **Step 4: 运行测试确认全部失败**

Run: `pytest tests/test_channel_wecom.py -v`
Expected: FAIL (ImportError — wecom.py 不存在)

- [x] **Step 5: 创建 wecom.py 实现**

```python
# src/chatcc/channel/wecom.py

"""WeCom (企业微信) AI Bot channel — WebSocket long-connection via wecom-aibot-sdk."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from loguru import logger
from wecom_aibot_sdk import WSClient

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

if TYPE_CHECKING:
    from chatcc.setup.ui import SetupUI


class WeComChannel(MessageChannel):

    @staticmethod
    def interactive_setup(
        ui: SetupUI,
        *,
        existing: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import questionary as q

        ex = existing or {}
        has_existing = existing is not None

        q.print("=== 企业微信智能机器人认证 ===", style="bold fg:cyan")
        bot_id = ui.prompt("请输入 Bot ID (机器人 ID)", default=ex.get("bot_id", ""))

        new_secret = ui.prompt_secret("请输入 Bot Secret", has_existing=has_existing)
        secret = new_secret if new_secret is not None else ex.get("secret", "")

        if not bot_id or not secret:
            raise ValueError("Bot ID 和 Secret 不能为空")

        default_allowed = ",".join(str(u) for u in ex.get("allowed_users", []))
        allowed = ui.prompt(
            "允许的用户 ID (逗号分隔, 留空允许所有)",
            default=default_allowed,
        )
        allowed_list = [u.strip() for u in allowed.split(",") if u.strip()]

        return {
            "bot_id": bot_id,
            "secret": secret,
            "allowed_users": allowed_list,
        }

    def __init__(self, config: dict[str, Any]):
        self._config = config
        self._bot_id: str = config.get("bot_id", "")
        self._secret: str = config.get("secret", "")
        self._allowed_users: list[str] = [
            str(u) for u in config.get("allowed_users", [])
        ]
        self._callback: Callable[[InboundMessage], Awaitable[None]] | None = None
        self._ws_client: WSClient | None = None

    async def start(self) -> None:
        if not self._bot_id or not self._secret:
            raise RuntimeError("WeCom bot_id/secret not configured")

        self._ws_client = WSClient(
            bot_id=self._bot_id,
            secret=self._secret,
            max_reconnect_attempts=-1,
        )

        self._ws_client.on("message.text", self._on_text)
        self._ws_client.on("message.mixed", self._on_text)
        self._ws_client.on("event.template_card_event", self._on_card_event)

        await self._ws_client.connect()
        logger.info("WeCom channel started (WebSocket)")

    async def stop(self) -> None:
        if self._ws_client:
            await self._ws_client.disconnect()
        logger.info("WeCom channel stopped")

    async def send(self, message: OutboundMessage) -> None:
        if not self._ws_client:
            raise RuntimeError("WeCom client not connected")

        if isinstance(message.content, RichMessage):
            payload = self.render(message.content)
        else:
            payload = {
                "msgtype": "markdown",
                "markdown": {"content": str(message.content)},
            }

        await self._ws_client.send_message(message.chat_id, payload)

    def render(self, message: RichMessage) -> dict[str, Any]:
        text_parts: list[str] = []
        buttons: list[dict[str, Any]] = []

        if message.project_tag:
            text_parts.append(f"[{message.project_tag}]")

        for el in message.elements:
            match el:
                case TextElement(content=content):
                    text_parts.append(content)
                case CodeElement(code=code, language=lang):
                    text_parts.append(f"```{lang}\n{code}\n```")
                case ActionGroup(buttons=action_buttons):
                    for b in action_buttons:
                        style = 1 if "/y" in b.command or b.style == "primary" else 2
                        buttons.append({
                            "text": b.label,
                            "style": style,
                            "key": b.command,
                        })
                case ProgressElement(description=desc, project=proj):
                    tag = f"[{proj}] " if proj else ""
                    text_parts.append(f"⏳ {tag}{desc}")
                case DividerElement():
                    text_parts.append("---")

        body_text = "\n\n".join(text_parts)

        if buttons:
            title = f"[{message.project_tag}] ChatCC" if message.project_tag else "ChatCC"
            return {
                "msgtype": "template_card",
                "template_card": {
                    "card_type": "button_interaction",
                    "main_title": {"title": title},
                    "sub_title_text": body_text,
                    "button_list": buttons,
                },
            }

        return {
            "msgtype": "markdown",
            "markdown": {"content": body_text},
        }

    def on_message(
        self, callback: Callable[[InboundMessage], Awaitable[None]]
    ) -> None:
        self._callback = callback

    def is_authenticated(self) -> bool:
        return bool(self._bot_id and self._secret)

    def _is_user_allowed(self, user_id: str) -> bool:
        if not self._allowed_users:
            return True
        return user_id in self._allowed_users

    async def _on_text(self, frame: dict[str, Any]) -> None:
        try:
            body = frame.get("body", {})
            sender = body.get("from", {})
            user_id = sender.get("user_id", "")
            chat_id = body.get("chat_id", user_id)
            msg_id = body.get("msg_id")

            text = body.get("text", {}).get("content", "")
            if not text:
                items = body.get("mixed", {}).get("items", [])
                text_parts = [
                    it.get("text", {}).get("content", "")
                    for it in items
                    if it.get("type") == "text"
                ]
                text = "\n".join(t for t in text_parts if t)

            logger.info("[WeCom] recv from={} chat={} text={!r}",
                        user_id, chat_id, text[:200])

            if not self._is_user_allowed(user_id):
                logger.warning("[WeCom] user {} not in allowed list, ignored", user_id)
                return

            if self._callback and text:
                msg = InboundMessage(
                    sender_id=user_id,
                    content=text,
                    chat_id=chat_id,
                    message_id=msg_id,
                    raw=frame,
                )
                await self._callback(msg)
        except Exception:
            logger.exception("[WeCom] error handling text message")

    async def _on_card_event(self, frame: dict[str, Any]) -> None:
        try:
            body = frame.get("body", {})
            event_key = body.get("event_key", "")
            sender = body.get("from", {})
            user_id = sender.get("user_id", "")
            chat_id = body.get("chat_id", user_id)

            logger.info("[WeCom] card event from={} chat={} key={!r}",
                        user_id, chat_id, event_key)

            if not event_key or not self._is_user_allowed(user_id):
                return

            if self._callback:
                msg = InboundMessage(
                    sender_id=user_id,
                    content=event_key,
                    chat_id=chat_id,
                    raw=frame,
                )
                await self._callback(msg)
        except Exception:
            logger.exception("[WeCom] error handling card event")
```

- [x] **Step 6: 运行测试**

Run: `pytest tests/test_channel_wecom.py tests/test_channel_factory.py -v`
Expected: 全部 PASS

- [x] **Step 7: Commit**

```bash
git add src/chatcc/channel/wecom.py src/chatcc/channel/factory.py \
        src/chatcc/config.py pyproject.toml tests/test_channel_wecom.py \
        tests/test_channel_factory.py
git commit -m "feat(channel): add WeCom AI Bot channel via WebSocket long-connection"
```

---

### Task 4: interactive_setup 测试

**Files:**
- Modify: `tests/test_channel_setup.py`

- [x] **Step 1: 写 interactive_setup 测试**

```python
# tests/test_channel_setup.py — 追加

def test_wecom_interactive_setup():
    from chatcc.channel.wecom import WeComChannel

    ui = FakeSetupUI(["bot-id-123", "secret-456", "zhangsan, lisi"])
    result = WeComChannel.interactive_setup(ui)

    assert result["bot_id"] == "bot-id-123"
    assert result["secret"] == "secret-456"
    assert result["allowed_users"] == ["zhangsan", "lisi"]


def test_wecom_interactive_setup_empty_creds():
    from chatcc.channel.wecom import WeComChannel

    ui = FakeSetupUI(["", "", ""])
    with pytest.raises(ValueError, match="不能为空"):
        WeComChannel.interactive_setup(ui)
```

注意: `FakeSetupUI` 需要支持 `prompt_secret` 方法。如果 `tests/test_setup_ui.py` 的 `FakeSetupUI` 还没有此方法，需先添加:

```python
# tests/test_setup_ui.py — FakeSetupUI 类中追加
    def prompt_secret(self, message: str, *, has_existing: bool = False) -> str | None:
        if self._answers:
            val = self._answers.pop(0)
            if not val and has_existing:
                return None
            return val
        return "" if not has_existing else None
```

- [x] **Step 2: 运行测试**

Run: `pytest tests/test_channel_setup.py -v`
Expected: 全部 PASS

- [x] **Step 3: Commit**

```bash
git add tests/test_channel_setup.py tests/test_setup_ui.py
git commit -m "test(wecom): add interactive_setup tests for WeCom channel"
```

---

## Chunk 2: 安装依赖 + 集成验证

### Task 5: 安装依赖并运行全量测试

- [x] **Step 1: 安装新依赖**

Run: `pip install -e ".[dev]"` 或 `uv sync`
Expected: `wecom-aibot-sdk` 安装成功

- [x] **Step 2: 全量测试**

Run: `pytest tests/ -v --ignore=tests/test_app_integration.py`
Expected: 全部 PASS，无引入的回归

- [x] **Step 3: 验证 factory 端到端**

```bash
python -c "from chatcc.channel.factory import create_channel; from chatcc.config import ChannelConfig; ch = create_channel(ChannelConfig(type='wecom', wecom={'bot_id': 'x', 'secret': 'y'})); print(type(ch), ch.is_authenticated())"
```
Expected: `<class 'chatcc.channel.wecom.WeComChannel'> True`

---

## 设计决策记录

### 1. 为什么用 send_message 而不是 reply?

`reply()` 需要原始 WebSocket frame，只能在 `_on_text` handler 中使用。但 chatcc 的架构是所有响应都走 `channel.send(OutboundMessage(...))` — 包括异步通知（审批卡片、任务状态、agent 回复等），这些发送时没有原始 frame 上下文。所以统一使用 `send_message(chatid, body)` 主动推送。

### 2. render() 的双模式输出

与飞书/Telegram 不同，WeCom 的 markdown 消息和模板卡片是完全不同的 msgtype。所以 `render()` 根据内容动态选择:
- 有 `ActionGroup` → `template_card` (button_interaction 类型)
- 纯文本/代码 → `markdown`

### 3. 暂不支持 reply_stream

`wecom-aibot-sdk` 提供了 `reply_stream()` 用于流式回复，体验很好。但 chatcc 目前发送完整消息，流式需要上层架构配合 (streaming callback)。记为后续增强。

### 4. Template Card 按钮样式映射

企微 button style: `1` = 蓝色主要, `2` = 黑色次要。
- 确认类按钮 (`/y`, style="primary") → style 1
- 其他 → style 2
