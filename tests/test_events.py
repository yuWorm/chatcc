from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from chatcc.claude.events import SessionProjectMap
from chatcc.claude.session import ProjectSession, TaskState


# --- SessionProjectMap ---


def test_register_and_get() -> None:
    spm = SessionProjectMap()
    spm.register("sess-1", "my-project")
    assert spm.get_project("sess-1") == "my-project"


def test_get_unknown() -> None:
    spm = SessionProjectMap()
    assert spm.get_project("unknown") is None


def test_unregister() -> None:
    spm = SessionProjectMap()
    spm.register("sess-1", "proj")
    spm.unregister("sess-1")
    assert spm.get_project("sess-1") is None


def test_clear() -> None:
    spm = SessionProjectMap()
    spm.register("a", "1")
    spm.register("b", "2")
    spm.clear()
    assert spm.get_project("a") is None


# --- consume_response ---


@pytest.fixture
def mock_project() -> MagicMock:
    p = MagicMock()
    p.name = "test-proj"
    p.path = "/tmp/test"
    p.config = MagicMock()
    p.config.permission_mode = "acceptEdits"
    p.config.setting_sources = ["project"]
    p.config.model = None
    return p


async def fake_response_stream(messages: list[MagicMock]):
    for msg in messages:
        yield msg


@pytest.mark.asyncio
async def test_consume_no_client_returns_none(mock_project: MagicMock) -> None:
    with patch("chatcc.claude.session.ClaudeSDKClient"):
        session = ProjectSession(mock_project)
    assert await session.consume_response() is None


@pytest.mark.asyncio
async def test_consume_forwards_text(mock_project: MagicMock) -> None:
    on_notify = AsyncMock()
    with patch("chatcc.claude.session.ClaudeSDKClient"):
        session = ProjectSession(mock_project, on_notification=on_notify)

    text_block = MagicMock()
    text_block.text = "Hello from Claude"

    assistant_msg = MagicMock()
    assistant_msg.type = "assistant"
    assistant_msg.content = [text_block]

    result_msg = MagicMock()
    result_msg.type = "result"
    result_msg.session_id = "sess-123"
    result_msg.cost_usd = 0.05

    mock_client = MagicMock()
    mock_client.receive_response = lambda: fake_response_stream(
        [assistant_msg, result_msg]
    )
    session.client = mock_client
    session.task_state = TaskState.RUNNING

    result = await session.consume_response()

    on_notify.assert_awaited_once_with("test-proj", "Hello from Claude")
    assert result is not None
    assert result["session_id"] == "sess-123"
    assert result["cost"] == 0.05
    assert session.task_state == TaskState.COMPLETED
    assert session.active_session_id == "sess-123"


@pytest.mark.asyncio
async def test_consume_result_omits_session_id_keeps_active(mock_project: MagicMock) -> None:
    """Message without session_id attribute falls back to active_session_id in result dict."""

    with patch("chatcc.claude.session.ClaudeSDKClient"):
        session = ProjectSession(mock_project)
    session.active_session_id = "existing"

    result_msg = SimpleNamespace(type="result", cost_usd=0.0)

    mock_client = MagicMock()
    mock_client.receive_response = lambda: fake_response_stream([result_msg])
    session.client = mock_client

    result = await session.consume_response()

    assert result is not None
    assert result["session_id"] == "existing"
    assert session.active_session_id == "existing"


@pytest.mark.asyncio
async def test_consume_cancelled_sets_state(mock_project: MagicMock) -> None:
    with patch("chatcc.claude.session.ClaudeSDKClient"):
        session = ProjectSession(mock_project)

    async def cancelled_stream():
        raise asyncio.CancelledError()
        yield  # pragma: no cover

    mock_client = MagicMock()
    mock_client.receive_response = lambda: cancelled_stream()
    session.client = mock_client
    session.task_state = TaskState.RUNNING

    with pytest.raises(asyncio.CancelledError):
        await session.consume_response()

    assert session.task_state == TaskState.CANCELLED


@pytest.mark.asyncio
async def test_consume_exception_sets_failed(mock_project: MagicMock) -> None:
    with patch("chatcc.claude.session.ClaudeSDKClient"):
        session = ProjectSession(mock_project)

    async def boom_stream():
        raise RuntimeError("stream error")
        yield  # pragma: no cover

    mock_client = MagicMock()
    mock_client.receive_response = lambda: boom_stream()
    session.client = mock_client
    session.task_state = TaskState.RUNNING

    with pytest.raises(RuntimeError, match="stream error"):
        await session.consume_response()

    assert session.task_state == TaskState.FAILED


@pytest.mark.asyncio
async def test_send_task_queries_and_consumes(mock_project: MagicMock) -> None:
    result_msg = MagicMock()
    result_msg.type = "result"
    result_msg.session_id = "sid-99"
    result_msg.cost_usd = 0.1

    mock_sdk = AsyncMock()
    mock_sdk.connect = AsyncMock()
    mock_sdk.query = AsyncMock()
    mock_sdk.receive_response = lambda: fake_response_stream([result_msg])

    with patch("chatcc.claude.session.ClaudeSDKClient", return_value=mock_sdk):
        session = ProjectSession(mock_project)
        out = await session.send_task("do it")

    mock_sdk.query.assert_awaited_once_with("do it")
    assert out is not None
    assert out["session_id"] == "sid-99"
    assert session.task_state == TaskState.COMPLETED
