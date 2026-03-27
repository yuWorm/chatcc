import pytest
import asyncio
from chatcc.approval.table import ApprovalTable


async def test_request_and_approve():
    table = ApprovalTable()
    future, approval_id = table.request_approval(
        project="myapp",
        tool_name="Bash",
        input_summary="rm -rf dist/",
    )
    assert approval_id == 1
    assert table.pending_count == 1
    table.approve(1)
    result = await asyncio.wait_for(future, timeout=1.0)
    assert result is True
    assert table.pending_count == 0


async def test_request_and_deny():
    table = ApprovalTable()
    future, approval_id = table.request_approval(
        project="myapp",
        tool_name="Bash",
        input_summary="sudo rm /",
    )
    assert approval_id == 1
    table.deny(1)
    result = await asyncio.wait_for(future, timeout=1.0)
    assert result is False


async def test_approve_oldest():
    table = ApprovalTable()
    f1, _ = table.request_approval("proj-a", "Bash", "cmd1")
    f2, _ = table.request_approval("proj-b", "Bash", "cmd2")
    assert table.pending_count == 2

    table.approve_oldest()
    r1 = await asyncio.wait_for(f1, timeout=1.0)
    assert r1 is True
    assert table.pending_count == 1


async def test_approve_all():
    table = ApprovalTable()
    f1, _ = table.request_approval("a", "Bash", "c1")
    f2, _ = table.request_approval("b", "Bash", "c2")
    table.approve_all()
    assert await asyncio.wait_for(f1, timeout=1.0) is True
    assert await asyncio.wait_for(f2, timeout=1.0) is True
    assert table.pending_count == 0


def test_list_pending():
    table = ApprovalTable()
    table.request_approval("proj", "Bash", "rm -rf /")
    pending = table.list_pending()
    assert len(pending) == 1
    assert pending[0].project == "proj"
