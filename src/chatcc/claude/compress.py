"""Compress a Claude Code session into a concise summary."""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ResultMessage,
    get_session_messages,
    query,
)
from loguru import logger

_COMPRESS_PROMPT = (
    "请将以下对话历史压缩为一段极简摘要。只保留：\n"
    "1. 项目当前状态（已完成/进行中的工作）\n"
    "2. 关键技术决策和约束\n"
    "3. 未完成的待办事项\n"
    "忽略所有工具调用细节和中间调试过程。用中文，控制在 300 字以内。\n\n"
    "---对话历史---\n{conversation}\n---\n\n"
    "极简摘要："
)


def format_messages(
    messages: list[Any],
    *,
    max_chars: int = 30_000,
) -> str:
    """Extract text-only content from session messages.

    Skips tool_use / tool_result blocks to keep the input lean.
    Truncates from the beginning when exceeding *max_chars* so the
    most recent context is preserved.
    """
    lines: list[str] = []
    for msg in messages:
        role = getattr(msg, "type", None) or "unknown"
        raw = getattr(msg, "message", None)
        if not isinstance(raw, dict):
            continue
        content = raw.get("content", "")
        if isinstance(content, str):
            lines.append(f"{role}: {content}")
        elif isinstance(content, list):
            texts = [
                b["text"]
                for b in content
                if isinstance(b, dict) and b.get("type") == "text" and b.get("text")
            ]
            if texts:
                lines.append(f"{role}: {''.join(texts)}")

    full = "\n".join(lines)
    if len(full) > max_chars:
        full = full[-max_chars:]
        cut = full.find("\n")
        if cut > 0:
            full = full[cut + 1 :]
    return full


async def compress_session(
    session_id: str,
    project_path: str,
    *,
    model: str | None = None,
) -> str | None:
    """Compress a session's conversation into a concise summary.

    Returns None if compression fails or the session has no meaningful content.
    Never raises — errors are logged and silently swallowed.
    """
    try:
        messages = get_session_messages(session_id, directory=project_path)
    except Exception:
        logger.opt(exception=True).debug(
            "Failed to read session {} messages", session_id[:12]
        )
        return None

    if not messages:
        return None

    conversation = format_messages(messages)
    if not conversation.strip():
        return None

    prompt = _COMPRESS_PROMPT.format(conversation=conversation)

    try:
        options = ClaudeAgentOptions(
            max_turns=1,
            model=model,
        )
        summary: str | None = None
        async for msg in query(prompt=prompt, options=options):
            if isinstance(msg, ResultMessage) and msg.result:
                summary = msg.result
        return summary
    except Exception:
        logger.opt(exception=True).debug(
            "Failed to compress session {}", session_id[:12]
        )
        return None
