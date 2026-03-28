from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from chatcc.claude.compress import format_messages


def _msg(role: str, text: str) -> MagicMock:
    """Create a mock SessionMessage."""
    m = MagicMock()
    m.type = role
    m.message = {"role": role, "content": text}
    return m


def _msg_with_blocks(role: str, blocks: list[dict]) -> MagicMock:
    m = MagicMock()
    m.type = role
    m.message = {"role": role, "content": blocks}
    return m


def test_format_messages_simple():
    msgs = [
        _msg("user", "帮我创建一个 hello.py"),
        _msg("assistant", "好的，我来创建文件"),
    ]
    result = format_messages(msgs)
    assert "user: 帮我创建一个 hello.py" in result
    assert "assistant: 好的，我来创建文件" in result


def test_format_messages_skips_tool_blocks():
    msgs = [
        _msg_with_blocks(
            "assistant",
            [
                {"type": "text", "text": "让我创建文件"},
                {"type": "tool_use", "name": "Write", "input": {"path": "hello.py"}},
            ],
        ),
    ]
    result = format_messages(msgs)
    assert "让我创建文件" in result
    assert "tool_use" not in result
    assert "Write" not in result


def test_format_messages_empty():
    assert format_messages([]) == ""


def test_format_messages_truncates_long_content():
    long_text = "x" * 100_000
    msgs = [_msg("user", long_text)]
    result = format_messages(msgs, max_chars=5000)
    assert len(result) <= 6000  # some overhead for role prefix


@pytest.mark.asyncio
@patch("chatcc.claude.compress.get_session_messages")
@patch("chatcc.claude.compress.query")
async def test_compress_session_success(mock_query, mock_get_msgs):
    from chatcc.claude.compress import ResultMessage, compress_session

    mock_get_msgs.return_value = [
        _msg("user", "创建用户认证模块"),
        _msg("assistant", "好的，我已经完成了 JWT 认证的实现"),
    ]

    async def fake_query(**kwargs):
        rm = MagicMock(spec=ResultMessage)
        rm.result = "完成了JWT认证模块"
        yield rm

    mock_query.side_effect = fake_query

    summary = await compress_session("sess-1", "/tmp/proj")
    assert summary is not None
    assert "JWT" in summary or "认证" in summary
    mock_get_msgs.assert_called_once()


@pytest.mark.asyncio
@patch("chatcc.claude.compress.get_session_messages")
async def test_compress_session_no_messages(mock_get_msgs):
    from chatcc.claude.compress import compress_session

    mock_get_msgs.return_value = []
    summary = await compress_session("sess-1", "/tmp/proj")
    assert summary is None


@pytest.mark.asyncio
@patch("chatcc.claude.compress.get_session_messages")
async def test_compress_session_error_returns_none(mock_get_msgs):
    from chatcc.claude.compress import compress_session

    mock_get_msgs.side_effect = RuntimeError("SDK error")
    summary = await compress_session("sess-1", "/tmp/proj")
    assert summary is None
