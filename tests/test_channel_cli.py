import pytest
from chatcc.channel.cli import CliChannel
from chatcc.channel.message import (
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


@pytest.mark.asyncio
async def test_cli_send_typing(capsys):
    channel = CliChannel()
    await channel.send_typing("cli")
    captured = capsys.readouterr()
    assert "思考中" in captured.out
