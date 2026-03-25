from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from chatcc.approval.table import ApprovalTable
from chatcc.claude.session import ProjectSession, _summarize_tool_input


@pytest.fixture
def mock_project(tmp_path: Path) -> MagicMock:
    p = MagicMock()
    p.name = "test-proj"
    p.path = str(tmp_path)
    p.config = MagicMock()
    p.config.permission_mode = "acceptEdits"
    p.config.setting_sources = ["project"]
    p.config.model = None
    return p


@pytest.mark.asyncio
async def test_safe_tool_allowed_immediately(mock_project: MagicMock) -> None:
    mock_allow = MagicMock()
    mock_deny = MagicMock()
    inner = Path(mock_project.path) / "file.py"
    inner.write_text("x", encoding="utf-8")
    with (
        patch("claude_agent_sdk.PermissionResultAllow", mock_allow),
        patch("claude_agent_sdk.PermissionResultDeny", mock_deny),
    ):
        session = ProjectSession(mock_project)
        await session._permission_handler(
            "Read", {"path": str(inner)}, None
        )
    mock_allow.assert_called_once_with(updated_input={"path": str(inner)})
    mock_deny.assert_not_called()


@pytest.mark.asyncio
async def test_forbidden_path_denied_immediately(mock_project: MagicMock) -> None:
    mock_allow = MagicMock()
    mock_deny = MagicMock()
    with (
        patch("claude_agent_sdk.PermissionResultAllow", mock_allow),
        patch("claude_agent_sdk.PermissionResultDeny", mock_deny),
    ):
        session = ProjectSession(mock_project)
        await session._permission_handler(
            "Read", {"path": "/etc/passwd"}, None
        )
    mock_deny.assert_called_once()
    call_kw = mock_deny.call_args.kwargs
    assert "边界" in call_kw.get("reason", "")
    mock_allow.assert_not_called()


@pytest.mark.asyncio
async def test_dangerous_with_approval_table_approves(
    mock_project: MagicMock,
) -> None:
    mock_allow = MagicMock()
    mock_deny = MagicMock()
    table = ApprovalTable()
    notify = AsyncMock()
    with (
        patch("claude_agent_sdk.PermissionResultAllow", mock_allow),
        patch("claude_agent_sdk.PermissionResultDeny", mock_deny),
    ):
        session = ProjectSession(
            mock_project,
            on_notification=notify,
            approval_table=table,
        )
        task = asyncio.create_task(
            session._permission_handler(
                "Bash", {"command": "rm -rf /tmp/x"}, None
            )
        )
        await asyncio.sleep(0)
        assert table.pending_count == 1
        table.approve(1)
        await task
    mock_allow.assert_called_once()
    mock_deny.assert_not_called()
    notify.assert_awaited()


@pytest.mark.asyncio
async def test_dangerous_with_approval_table_user_denies(
    mock_project: MagicMock,
) -> None:
    mock_allow = MagicMock()
    mock_deny = MagicMock()
    table = ApprovalTable()
    notify = AsyncMock()
    with (
        patch("claude_agent_sdk.PermissionResultAllow", mock_allow),
        patch("claude_agent_sdk.PermissionResultDeny", mock_deny),
    ):
        session = ProjectSession(
            mock_project,
            on_notification=notify,
            approval_table=table,
        )
        task = asyncio.create_task(
            session._permission_handler(
                "Bash", {"command": "rm -rf /tmp/x"}, None
            )
        )
        await asyncio.sleep(0)
        table.deny(1)
        await task
    mock_deny.assert_called_once()
    call_kw = mock_deny.call_args.kwargs
    assert "拒绝" in call_kw.get("reason", "")
    mock_allow.assert_not_called()


@pytest.mark.asyncio
async def test_dangerous_fallback_on_permission(mock_project: MagicMock) -> None:
    mock_allow = MagicMock()
    mock_deny = MagicMock()
    on_perm = AsyncMock(return_value=True)
    with (
        patch("claude_agent_sdk.PermissionResultAllow", mock_allow),
        patch("claude_agent_sdk.PermissionResultDeny", mock_deny),
    ):
        session = ProjectSession(mock_project, on_permission=on_perm)
        await session._permission_handler(
            "Bash", {"command": "rm -rf /tmp/x"}, None
        )
    on_perm.assert_awaited_once()
    mock_allow.assert_called_once()
    mock_deny.assert_not_called()


@pytest.mark.asyncio
async def test_dangerous_on_permission_denies(mock_project: MagicMock) -> None:
    mock_allow = MagicMock()
    mock_deny = MagicMock()
    on_perm = AsyncMock(return_value=False)
    with (
        patch("claude_agent_sdk.PermissionResultAllow", mock_allow),
        patch("claude_agent_sdk.PermissionResultDeny", mock_deny),
    ):
        session = ProjectSession(mock_project, on_permission=on_perm)
        await session._permission_handler(
            "Bash", {"command": "rm -rf /tmp/x"}, None
        )
    mock_deny.assert_called_once()
    mock_allow.assert_not_called()


@pytest.mark.asyncio
async def test_dangerous_no_mechanism_denies_by_default(
    mock_project: MagicMock,
) -> None:
    mock_allow = MagicMock()
    mock_deny = MagicMock()
    with (
        patch("claude_agent_sdk.PermissionResultAllow", mock_allow),
        patch("claude_agent_sdk.PermissionResultDeny", mock_deny),
    ):
        session = ProjectSession(mock_project)
        await session._permission_handler(
            "Bash", {"command": "rm -rf /tmp/x"}, None
        )
    mock_deny.assert_called_once()
    call_kw = mock_deny.call_args.kwargs
    assert "无审批" in call_kw.get("reason", "")
    mock_allow.assert_not_called()


def test_build_options_wires_permission_when_approval_table_only(
    mock_project: MagicMock,
) -> None:
    table = ApprovalTable()
    session = ProjectSession(mock_project, approval_table=table)
    options = session._build_options()
    assert options.can_use_tool is not None
    assert getattr(options.can_use_tool, "__self__", None) is session
    assert getattr(options.can_use_tool, "__func__", None) is ProjectSession._permission_handler


def test_summarize_tool_input_bash() -> None:
    s = _summarize_tool_input("Bash", {"command": "echo hi"})
    assert "echo hi" in s


def test_summarize_tool_input_write() -> None:
    s = _summarize_tool_input("Write", {"path": "/proj/a.py"})
    assert "写入" in s and "a.py" in s


def test_summarize_tool_input_other() -> None:
    s = _summarize_tool_input("Foo", {"x": 1})
    assert "Foo" in s
