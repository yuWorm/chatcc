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
    assert result == "approve"
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
    assert result == "deny"


async def test_approve_oldest():
    table = ApprovalTable()
    f1, _ = table.request_approval("proj-a", "Bash", "cmd1")
    f2, _ = table.request_approval("proj-b", "Bash", "cmd2")
    assert table.pending_count == 2

    table.approve_oldest()
    r1 = await asyncio.wait_for(f1, timeout=1.0)
    assert r1 == "approve"
    assert table.pending_count == 1


async def test_approve_all():
    table = ApprovalTable()
    f1, _ = table.request_approval("a", "Bash", "c1")
    f2, _ = table.request_approval("b", "Bash", "c2")
    table.approve_all()
    assert await asyncio.wait_for(f1, timeout=1.0) == "approve"
    assert await asyncio.wait_for(f2, timeout=1.0) == "approve"
    assert table.pending_count == 0


def test_list_pending():
    table = ApprovalTable()
    table.request_approval("proj", "Bash", "rm -rf /")
    pending = table.list_pending()
    assert len(pending) == 1
    assert pending[0].project == "proj"


async def test_resolve_binary():
    table = ApprovalTable()
    future, aid = table.request_approval("p", "Bash", "x")
    assert table.resolve(aid, "approve") is True
    assert await asyncio.wait_for(future, timeout=1.0) == "approve"


async def test_resolve_binary_invalid_value():
    table = ApprovalTable()
    future, aid = table.request_approval("p", "Bash", "x")
    assert table.resolve(aid, "nope") is False
    assert table.pending_count == 1
    table.approve(aid)
    assert await asyncio.wait_for(future, timeout=1.0) == "approve"


async def test_resolve_choice():
    table = ApprovalTable()
    choices = [("queue", "Queue"), ("interrupt", "Interrupt")]
    future, aid = table.request_choice("p", "Task", "conflict", choices)
    assert table.get_pending(aid) is not None
    assert table.get_pending(aid).choices == choices
    assert table.resolve(aid, "interrupt") is True
    assert await asyncio.wait_for(future, timeout=1.0) == "interrupt"
    assert table.get_pending(aid) is None


async def test_resolve_choice_invalid_value():
    table = ApprovalTable()
    future, aid = table.request_choice(
        "p", "Task", "c", [("a", "A"), ("b", "B")],
    )
    assert table.resolve(aid, "c") is False
    assert not future.done()
    assert table.resolve(aid, "b") is True
    assert await asyncio.wait_for(future, timeout=1.0) == "b"


async def test_resolve_unknown_id():
    table = ApprovalTable()
    assert table.resolve(999, "approve") is False


async def test_request_choice_is_not_binary():
    table = ApprovalTable()
    f_choice, choice_id = table.request_choice(
        "p", "T", "msg", [("x", "X")],
    )
    f_bin, bin_id = table.request_approval("p", "Bash", "cmd")
    assert table.pending_count == 2
    table.approve_all()
    assert await asyncio.wait_for(f_bin, timeout=1.0) == "approve"
    assert not f_choice.done()
    assert table.pending_count == 1
    assert table.get_pending(choice_id) is not None
    table.resolve(choice_id, "x")
    assert await asyncio.wait_for(f_choice, timeout=1.0) == "x"


async def test_approve_oldest_skips_choice_only_queue():
    table = ApprovalTable()
    fc, _ = table.request_choice("p", "T", "c", [("q", "Q")])
    fb, _ = table.request_approval("p", "Bash", "b")
    table.approve_oldest()
    assert await asyncio.wait_for(fb, timeout=1.0) == "approve"
    assert not fc.done()


def test_get_pending():
    table = ApprovalTable()
    _, aid = table.request_approval("proj", "Bash", "rm")
    p = table.get_pending(aid)
    assert p is not None
    assert p.id == aid
    assert p.is_binary is True
    table.approve(aid)
    assert table.get_pending(aid) is None
