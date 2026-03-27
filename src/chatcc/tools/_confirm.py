"""Inline confirmation helpers for main-agent tools.

These functions encapsulate the pattern:
  request choice → send card → await future → return user's choice.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from chatcc.approval.table import ApprovalTable
from chatcc.channel.compose import compose_conflict_choice, compose_confirmation
from chatcc.channel.message import OutboundMessage


async def confirm_conflict(
    table: ApprovalTable,
    send_fn: Callable[[OutboundMessage], Awaitable[None]],
    chat_id: str,
    project: str,
    prompt: str,
) -> str:
    """Present queue/interrupt/cancel choice and return the user's pick.

    If send_fn fails, returns "cancel" and cleans up the pending item.
    """
    choices = [
        ("📋 排队等待", "queue"),
        ("⚡ 打断执行", "interrupt"),
        ("❌ 取消", "cancel"),
    ]
    future, aid = table.request_choice(
        project=project,
        tool_name="send_to_claude",
        input_summary=f"任务冲突: {prompt[:100]}",
        choices=choices,
    )
    try:
        msg = compose_conflict_choice(project, prompt, aid)
        await send_fn(OutboundMessage(chat_id=chat_id, content=msg))
    except Exception:
        table.resolve(aid, "cancel")
        return "cancel"
    return await future


async def confirm_action(
    table: ApprovalTable,
    send_fn: Callable[[OutboundMessage], Awaitable[None]],
    chat_id: str,
    project: str,
    description: str,
) -> bool:
    """Present approve/deny confirmation and return True if approved.

    If send_fn fails, returns False and cleans up the pending item.
    """
    future, aid = table.request_approval(
        project=project,
        tool_name="confirm",
        input_summary=description,
    )
    try:
        msg = compose_confirmation(project, description, aid)
        await send_fn(OutboundMessage(chat_id=chat_id, content=msg))
    except Exception:
        table.resolve(aid, "deny")
        return False
    result = await future
    return result == "approve"
