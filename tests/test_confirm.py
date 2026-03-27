import asyncio

from chatcc.approval.table import ApprovalTable
from chatcc.channel.message import OutboundMessage, RichMessage
from chatcc.tools._confirm import confirm_action, confirm_conflict


async def test_confirm_conflict_queue():
    table = ApprovalTable()
    sent: list[OutboundMessage] = []

    async def mock_send(msg: OutboundMessage):
        sent.append(msg)

    async def auto_resolve():
        while table.pending_count == 0:
            await asyncio.sleep(0.01)
        items = table.list_pending()
        table.resolve(items[0].id, "queue")

    task = asyncio.create_task(auto_resolve())
    result = await confirm_conflict(
        table=table,
        send_fn=mock_send,
        chat_id="c1",
        project="myapp",
        prompt="build feature",
    )
    assert result == "queue"
    assert len(sent) == 1
    assert isinstance(sent[0].content, RichMessage)
    await task


async def test_confirm_conflict_cancel():
    table = ApprovalTable()
    sent: list[OutboundMessage] = []

    async def mock_send(msg: OutboundMessage):
        sent.append(msg)

    async def auto_resolve():
        while table.pending_count == 0:
            await asyncio.sleep(0.01)
        items = table.list_pending()
        table.resolve(items[0].id, "cancel")

    task = asyncio.create_task(auto_resolve())
    result = await confirm_conflict(
        table=table,
        send_fn=mock_send,
        chat_id="c1",
        project="p",
        prompt="x",
    )
    assert result == "cancel"
    await task


async def test_confirm_action_approved():
    table = ApprovalTable()
    sent: list[OutboundMessage] = []

    async def mock_send(msg: OutboundMessage):
        sent.append(msg)

    async def auto_approve():
        while table.pending_count == 0:
            await asyncio.sleep(0.01)
        items = table.list_pending()
        table.resolve(items[0].id, "approve")

    task = asyncio.create_task(auto_approve())
    result = await confirm_action(
        table=table,
        send_fn=mock_send,
        chat_id="c1",
        project="proj",
        description="确定要中断？",
    )
    assert result is True
    assert len(sent) == 1
    await task


async def test_confirm_action_denied():
    table = ApprovalTable()
    sent: list[OutboundMessage] = []

    async def mock_send(msg: OutboundMessage):
        sent.append(msg)

    async def auto_deny():
        while table.pending_count == 0:
            await asyncio.sleep(0.01)
        items = table.list_pending()
        table.resolve(items[0].id, "deny")

    task = asyncio.create_task(auto_deny())
    result = await confirm_action(
        table=table,
        send_fn=mock_send,
        chat_id="c1",
        project="proj",
        description="确定？",
    )
    assert result is False
    await task


async def test_confirm_conflict_send_fails():
    """When send_fn raises, should return 'cancel' and clean up."""
    table = ApprovalTable()

    async def bad_send(msg: OutboundMessage):
        raise ConnectionError("channel down")

    result = await confirm_conflict(
        table=table,
        send_fn=bad_send,
        chat_id="c",
        project="p",
        prompt="x",
    )
    assert result == "cancel"
    assert table.pending_count == 0


async def test_confirm_action_send_fails():
    """When send_fn raises, should return False and clean up."""
    table = ApprovalTable()

    async def bad_send(msg: OutboundMessage):
        raise ConnectionError("channel down")

    result = await confirm_action(
        table=table,
        send_fn=bad_send,
        chat_id="c",
        project="p",
        description="test",
    )
    assert result is False
    assert table.pending_count == 0
