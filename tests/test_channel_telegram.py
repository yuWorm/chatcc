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
    rich = RichMessage(
        elements=[CodeElement(code="print('hello')", language="python")]
    )
    text, _ = channel.render(rich)
    assert "print('hello')" in text


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
            ActionGroup(
                buttons=[
                    ActionButton(label="✅ 允许", command="/y 3"),
                    ActionButton(label="❌ 拒绝", command="/n 3"),
                ]
            ),
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


@pytest.mark.asyncio
async def test_send_typing_calls_chat_action(channel):
    from unittest.mock import AsyncMock
    channel._bot = AsyncMock()
    await channel.send_typing("12345")
    channel._bot.send_chat_action.assert_called_once()
    call_kwargs = channel._bot.send_chat_action.call_args
    assert call_kwargs.kwargs["chat_id"] == "12345"


@pytest.mark.asyncio
async def test_send_typing_noop_without_bot(channel):
    channel._bot = None
    await channel.send_typing("12345")
