from unittest.mock import AsyncMock, MagicMock

import pytest

from chatcc.app import Application
from chatcc.channel.message import InboundMessage, OutboundMessage, RichMessage, TextElement
from chatcc.config import AppConfig


@pytest.fixture
def app(tmp_path):
    """Create Application with data_dir pointing to tmp_path."""
    config = AppConfig(data_dir=str(tmp_path), workspace=str(tmp_path))
    application = Application(config=config)
    application.channel = AsyncMock()
    return application


def test_app_has_all_subsystems(app):
    assert app.project_manager is not None
    assert app.approval_table is not None
    assert app.cost_tracker is not None
    assert app.history is not None
    assert app.longterm_memory is not None
    assert app.task_manager is not None
    assert app.service_manager is not None


async def test_handle_y_approve_oldest(app):
    app.approval_table.request_approval("proj", "Bash", "rm -rf /")
    msg = InboundMessage(sender_id="u1", chat_id="chat-1", content="/y")
    await app._handle_command("/y", [], msg)

    app.channel.send.assert_awaited_once()
    outbound = app.channel.send.await_args.args[0]
    assert outbound.chat_id == "chat-1"
    assert "已确认最早的待审批项" in outbound.content
    assert app.approval_table.pending_count == 0


async def test_handle_n_deny_oldest(app):
    app.approval_table.request_approval("proj", "Bash", "sudo")
    msg = InboundMessage(sender_id="u1", chat_id="chat-1", content="/n")
    await app._handle_command("/n", [], msg)

    app.channel.send.assert_awaited_once()
    outbound = app.channel.send.await_args.args[0]
    assert outbound.chat_id == "chat-1"
    assert "已拒绝最早的待审批项" in outbound.content
    assert app.approval_table.pending_count == 0


async def test_handle_pending_empty(app):
    msg = InboundMessage(sender_id="u1", chat_id="c2", content="/pending")
    await app._handle_command("/pending", [], msg)

    outbound = app.channel.send.await_args.args[0]
    assert isinstance(outbound.content, RichMessage)
    assert any(
        isinstance(el, TextElement) and "暂无待确认操作" in el.content
        for el in outbound.content.elements
    )


async def test_handle_status(app):
    msg = InboundMessage(sender_id="u1", chat_id="c3", content="/status")
    await app._handle_command("/status", [], msg)

    outbound = app.channel.send.await_args.args[0]
    assert "项目数: 0" in outbound.content
    assert "待审批: 0" in outbound.content
    assert "主 Agent 费用" in outbound.content


async def test_agent_message_records_history(app):
    app.dispatcher = MagicMock()
    app.dispatcher.agent.run = AsyncMock(
        return_value=MagicMock(output="助手回复内容")
    )

    msg = InboundMessage(
        sender_id="u1",
        chat_id="c4",
        content="用户问题",
    )
    await app._handle_agent_message(msg)

    messages = app.history.get_messages()
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "用户问题"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "助手回复内容"

    app.channel.send.assert_awaited_once()
    outbound = app.channel.send.await_args.args[0]
    assert outbound.content == "助手回复内容"


async def test_send_to_channel(app):
    await app._send_to_channel(OutboundMessage(chat_id="x", content="hi"))
    app.channel.send.assert_awaited_once()
