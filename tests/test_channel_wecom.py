import pytest
from unittest.mock import AsyncMock

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


@pytest.fixture
def restricted_channel():
    config = {
        "bot_id": "test-bot-id",
        "secret": "test-bot-secret",
        "allowed_users": ["zhangsan"],
    }
    return WeComChannel(config)


# --- Authentication ---

def test_not_authenticated_without_credentials():
    ch = WeComChannel({})
    assert ch.is_authenticated() is False


def test_authenticated_with_credentials(channel):
    assert channel.is_authenticated() is True


# --- User allowed ---

def test_empty_allowed_users_allows_all(channel):
    assert channel._is_user_allowed("anyone") is True


def test_restricted_list_allows_listed_user(restricted_channel):
    assert restricted_channel._is_user_allowed("zhangsan") is True


def test_restricted_list_blocks_unlisted_user(restricted_channel):
    assert restricted_channel._is_user_allowed("lisi") is False


# --- render() text-only ---

def test_render_text_only(channel):
    rich = RichMessage(elements=[TextElement(content="Hello")])
    result = channel.render(rich)
    assert result["msgtype"] == "markdown"
    assert "Hello" in result["markdown"]["content"]


# --- render() with project_tag ---

def test_render_with_project_tag(channel):
    rich = RichMessage(
        elements=[TextElement(content="test")],
        project_tag="myapp",
    )
    result = channel.render(rich)
    assert "[myapp]" in result["markdown"]["content"]


# --- render() code block ---

def test_render_code_block(channel):
    rich = RichMessage(
        elements=[CodeElement(code="print('hello')", language="python")]
    )
    result = channel.render(rich)
    assert "print('hello')" in result["markdown"]["content"]
    assert "```python" in result["markdown"]["content"]


# --- render() progress ---

def test_render_progress(channel):
    rich = RichMessage(
        elements=[ProgressElement(description="正在执行...", project="myapp")]
    )
    result = channel.render(rich)
    assert "正在执行" in result["markdown"]["content"]
    assert "[myapp]" in result["markdown"]["content"]


# --- render() divider ---

def test_render_divider(channel):
    rich = RichMessage(
        elements=[
            TextElement(content="above"),
            DividerElement(),
            TextElement(content="below"),
        ]
    )
    result = channel.render(rich)
    content = result["markdown"]["content"]
    assert "---" in content
    assert "above" in content
    assert "below" in content


# --- render() with action buttons ---

def test_render_action_buttons(channel):
    rich = RichMessage(
        elements=[
            ActionGroup(
                buttons=[
                    ActionButton(label="允许", command="/y 1"),
                    ActionButton(label="拒绝", command="/n 1"),
                ]
            ),
        ]
    )
    result = channel.render(rich)
    assert result["msgtype"] == "template_card"
    buttons = result["template_card"]["button_list"]
    assert len(buttons) == 2
    assert buttons[0]["text"] == "允许"
    assert buttons[0]["key"] == "/y 1"
    assert buttons[0]["style"] == 1  # primary for /y
    assert buttons[1]["style"] == 2  # secondary for /n


# --- render() full approval message ---

def test_render_full_approval_message(channel):
    rich = RichMessage(
        project_tag="myapp",
        elements=[
            TextElement(content="Claude Code 请求执行危险操作:"),
            CodeElement(code="rm -rf dist/", language="bash"),
            TextElement(content="工具: Bash | 请求 ID: #3"),
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
    assert "[myapp]" in result["template_card"]["main_title"]["title"]
    assert "rm -rf dist/" in result["template_card"]["sub_title_text"]
    assert len(result["template_card"]["button_list"]) == 2


# --- _on_text handler ---

@pytest.mark.asyncio
async def test_on_text_dispatches_callback(channel):
    callback = AsyncMock()
    channel.on_message(callback)

    frame = {
        "body": {
            "msg_id": "msg-001",
            "chat_id": "wrkSFfCgAAxxxxxx",
            "from": {"user_id": "zhangsan", "name": "张三"},
            "text": {"content": "你好"},
        }
    }
    await channel._on_text(frame)

    callback.assert_called_once()
    msg = callback.call_args[0][0]
    assert msg.sender_id == "zhangsan"
    assert msg.content == "你好"
    assert msg.chat_id == "wrkSFfCgAAxxxxxx"
    assert msg.message_id == "msg-001"
    assert msg.raw is frame


# --- _on_text handler with mixed message ---

@pytest.mark.asyncio
async def test_on_text_mixed_message(channel):
    callback = AsyncMock()
    channel.on_message(callback)

    frame = {
        "body": {
            "from": {"user_id": "zhangsan"},
            "chat_id": "wrkSFfCgAAxxxxxx",
            "mixed": {
                "items": [
                    {"type": "text", "text": {"content": "hello"}},
                    {"type": "image", "image": {"url": "http://example.com/img.png"}},
                    {"type": "text", "text": {"content": "world"}},
                ]
            },
        }
    }
    await channel._on_text(frame)

    callback.assert_called_once()
    msg = callback.call_args[0][0]
    assert msg.content == "hello\nworld"


# --- _on_text ignores non-allowed users ---

@pytest.mark.asyncio
async def test_on_text_ignores_non_allowed_user(restricted_channel):
    callback = AsyncMock()
    restricted_channel.on_message(callback)

    frame = {
        "body": {
            "msg_id": "msg-002",
            "chat_id": "wrkSFfCgAAxxxxxx",
            "from": {"user_id": "lisi"},
            "text": {"content": "你好"},
        }
    }
    await restricted_channel._on_text(frame)

    callback.assert_not_called()


# --- _on_card_event handler ---

@pytest.mark.asyncio
async def test_on_card_event_dispatches_callback(channel):
    callback = AsyncMock()
    channel.on_message(callback)

    frame = {
        "body": {
            "event_key": "/y 3",
            "from": {"user_id": "zhangsan"},
            "chat_id": "wrkSFfCgAAxxxxxx",
        }
    }
    await channel._on_card_event(frame)

    callback.assert_called_once()
    msg = callback.call_args[0][0]
    assert msg.sender_id == "zhangsan"
    assert msg.content == "/y 3"
    assert msg.chat_id == "wrkSFfCgAAxxxxxx"
    assert msg.raw is frame


# --- _on_card_event ignores non-allowed users ---

@pytest.mark.asyncio
async def test_on_card_event_ignores_non_allowed_user(restricted_channel):
    callback = AsyncMock()
    restricted_channel.on_message(callback)

    frame = {
        "body": {
            "event_key": "/y 3",
            "from": {"user_id": "lisi"},
            "chat_id": "wrkSFfCgAAxxxxxx",
        }
    }
    await restricted_channel._on_card_event(frame)

    callback.assert_not_called()
