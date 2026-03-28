from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from chatcc.claude.session import TaskState
from chatcc.claude.task_manager import TaskManager
from chatcc.config import SessionPolicyConfig
from chatcc.project.models import SessionRecord
from chatcc.project.session_log import SessionLog


@pytest.fixture
def mock_pm(tmp_path):
    pm = MagicMock()
    project_a = MagicMock()
    project_a.name = "proj-a"
    project_a.path = "/tmp/proj-a"
    project_b = MagicMock()
    project_b.name = "proj-b"
    project_b.path = "/tmp/proj-b"
    pm.get_project.side_effect = lambda name: {"proj-a": project_a, "proj-b": project_b}.get(name)

    dir_a = tmp_path / "proj-a"
    dir_a.mkdir()
    dir_b = tmp_path / "proj-b"
    dir_b.mkdir()
    pm.project_dir.side_effect = lambda name: {
        "proj-a": dir_a,
        "proj-b": dir_b,
    }.get(name)
    return pm


def test_get_session_creates_session_for_known_project(mock_pm):
    tm = TaskManager(project_manager=mock_pm)
    s = tm.get_session("proj-a")
    assert s is not None
    assert s.project.name == "proj-a"
    assert tm.get_session("proj-a") is s


def test_get_session_returns_none_for_unknown_project(mock_pm):
    tm = TaskManager(project_manager=mock_pm)
    assert tm.get_session("unknown") is None


@pytest.mark.asyncio
async def test_submit_task_unknown_project(mock_pm):
    tm = TaskManager(project_manager=mock_pm)
    result = await tm.submit_task("nope", "x")
    assert "不存在" in result.message


@pytest.mark.asyncio
@patch("chatcc.claude.task_manager.ProjectSession")
async def test_submit_task_success(MockSession, mock_pm):
    mock_client = AsyncMock()
    mock_client.query = AsyncMock()

    mock_session = AsyncMock()
    mock_session.project = mock_pm.get_project("proj-a")
    mock_session.task_state = TaskState.IDLE
    mock_session.active_session_id = None
    mock_session.client = None
    mock_session.ensure_connected = AsyncMock(return_value=mock_client)
    mock_session.consume_response = AsyncMock(
        return_value={"session_id": "sess-1", "cost": 0.01}
    )
    MockSession.return_value = mock_session

    tm = TaskManager(project_manager=mock_pm)
    result = await tm.submit_task("proj-a", "build feature X")
    assert "已提交" in result.message

    await asyncio.wait_for(_wait_client_query(mock_client), timeout=2.0)
    mock_client.query.assert_awaited_once_with("build feature X")
    await asyncio.sleep(0.05)
    assert mock_session.task_state == TaskState.COMPLETED


async def _wait_client_query(mock_client: AsyncMock, timeout: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if mock_client.query.await_count > 0:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("client.query was not awaited in time")


@pytest.mark.asyncio
@patch("chatcc.claude.task_manager.ProjectSession")
async def test_submit_task_rejects_when_running(MockSession, mock_pm):
    mock_session = AsyncMock()
    mock_session.project = mock_pm.get_project("proj-a")
    mock_session.task_state = TaskState.IDLE
    MockSession.return_value = mock_session

    tm = TaskManager(project_manager=mock_pm)
    tm.get_session("proj-a")
    tm._current_tasks["proj-a"] = MagicMock()

    second = await tm.submit_task("proj-a", "second")
    assert "正在执行" in second.message or "请等待" in second.message


@pytest.mark.asyncio
@patch("chatcc.claude.task_manager.ProjectSession")
async def test_submit_task_parallel_across_projects(MockSession, mock_pm):
    by_name: dict[str, AsyncMock] = {}

    def make_session(*_a, project, **_kw):
        name = project.name
        if name in by_name:
            return by_name[name]
        s = AsyncMock()
        s.project = project
        s.task_state = TaskState.IDLE
        s.active_session_id = None
        s.client = None
        mc = AsyncMock()
        mc.query = AsyncMock()
        s.ensure_connected = AsyncMock(return_value=mc)
        s.consume_response = AsyncMock(
            return_value={"session_id": f"sess-{name}", "cost": 0.01}
        )
        by_name[name] = s
        return s

    MockSession.side_effect = make_session

    tm = TaskManager(project_manager=mock_pm)
    await tm.submit_task("proj-a", "a1")
    await tm.submit_task("proj-b", "b1")
    await asyncio.sleep(0.15)

    assert by_name["proj-a"].ensure_connected.await_count >= 1
    assert by_name["proj-b"].ensure_connected.await_count >= 1


async def _long_consume_response() -> dict[str, object]:
    await asyncio.sleep(3600)
    return {}


@pytest.mark.asyncio
@patch("chatcc.claude.task_manager.ProjectSession")
async def test_interrupt_task(MockSession, mock_pm):
    mock_client = AsyncMock()
    mock_client.query = AsyncMock()

    mock_session = MagicMock()
    mock_session.project = mock_pm.get_project("proj-a")
    mock_session.task_state = TaskState.IDLE
    mock_session.active_session_id = None
    mock_session.client = None
    mock_session.ensure_connected = AsyncMock(return_value=mock_client)
    mock_session.consume_response = _long_consume_response
    mock_session.interrupt = AsyncMock()
    MockSession.return_value = mock_session

    tm = TaskManager(project_manager=mock_pm)
    await tm.submit_task("proj-a", "long")
    await asyncio.sleep(0.02)

    msg = await tm.interrupt_task("proj-a")
    assert "已中断" in msg
    mock_session.interrupt.assert_awaited()
    await tm.shutdown()


@pytest.mark.asyncio
async def test_interrupt_no_session(mock_pm):
    tm = TaskManager(project_manager=mock_pm)
    msg = await tm.interrupt_task("proj-a")
    assert "无活跃会话" in msg


@pytest.mark.asyncio
@patch("chatcc.claude.task_manager.ProjectSession")
async def test_interrupt_not_running(MockSession, mock_pm):
    mock_session = MagicMock()
    mock_session.project = mock_pm.get_project("proj-a")
    mock_session.task_state = TaskState.IDLE
    MockSession.return_value = mock_session

    tm = TaskManager(project_manager=mock_pm)
    tm.get_session("proj-a")
    msg = await tm.interrupt_task("proj-a")
    assert "无运行中的任务" in msg


def test_get_task_status(mock_pm):
    tm = TaskManager(project_manager=mock_pm)
    assert tm.get_task_status("proj-a") == "无活跃会话"
    s = tm.get_session("proj-a")
    assert s is not None
    assert tm.get_task_status("proj-a") == "idle"


def test_get_all_status(mock_pm):
    tm = TaskManager(project_manager=mock_pm)
    tm.get_session("proj-a")
    tm.get_session("proj-b")
    assert tm.get_all_status() == {"proj-a": "idle", "proj-b": "idle"}


@pytest.mark.asyncio
@patch("chatcc.claude.task_manager.ProjectSession")
async def test_shutdown_cancels_and_disconnects(MockSession, mock_pm):
    mock_client = AsyncMock()
    mock_client.query = AsyncMock()

    mock_session = MagicMock()
    mock_session.project = mock_pm.get_project("proj-a")
    mock_session.task_state = TaskState.IDLE
    mock_session.active_session_id = None
    mock_session.client = None
    mock_session.ensure_connected = AsyncMock(return_value=mock_client)
    mock_session.consume_response = _long_consume_response
    mock_session.disconnect = AsyncMock()
    MockSession.return_value = mock_session

    tm = TaskManager(project_manager=mock_pm)
    await tm.submit_task("proj-a", "x")
    await asyncio.sleep(0.02)
    await tm.shutdown()

    mock_session.disconnect.assert_awaited()
    assert tm.get_all_status() == {}


@pytest.mark.asyncio
@patch("chatcc.claude.task_manager.ProjectSession")
async def test_run_task_sets_failed_on_error(MockSession, mock_pm):
    mock_client = AsyncMock()
    mock_client.query = AsyncMock(side_effect=RuntimeError("boom"))

    mock_session = AsyncMock()
    mock_session.project = mock_pm.get_project("proj-a")
    mock_session.task_state = TaskState.IDLE
    mock_session.active_session_id = None
    mock_session.client = None
    mock_session.ensure_connected = AsyncMock(return_value=mock_client)
    mock_session.consume_response = AsyncMock()
    MockSession.return_value = mock_session

    tm = TaskManager(project_manager=mock_pm)
    await tm.submit_task("proj-a", "x")
    await asyncio.sleep(0.15)

    assert mock_session.task_state == TaskState.FAILED


# ── Session recovery on get_session ───────────────────────────────


def test_get_session_restores_active_session_id(mock_pm):
    """After a process restart, get_session should restore active_session_id
    from sessions.jsonl so the SDK can resume the previous conversation."""
    data_dir = mock_pm.project_dir("proj-a")
    sl = SessionLog(data_dir / "sessions.jsonl")
    sl.append(SessionRecord(
        session_id="sess-from-last-run",
        project_name="proj-a",
        task_ids=["t1"],
        total_cost_usd=0.01,
        status="active",
    ))

    tm = TaskManager(project_manager=mock_pm)
    session = tm.get_session("proj-a")
    assert session is not None
    assert session.active_session_id == "sess-from-last-run"


def test_get_session_does_not_restore_closed_session(mock_pm):
    """Closed sessions should not be auto-restored."""
    data_dir = mock_pm.project_dir("proj-a")
    sl = SessionLog(data_dir / "sessions.jsonl")
    sl.append(SessionRecord(
        session_id="sess-old",
        project_name="proj-a",
        status="closed",
    ))

    tm = TaskManager(project_manager=mock_pm)
    session = tm.get_session("proj-a")
    assert session is not None
    assert session.active_session_id is None


def test_get_session_no_session_log(mock_pm):
    """When project has no session log, active_session_id stays None."""
    mock_pm.project_dir.side_effect = lambda name: None

    tm = TaskManager(project_manager=mock_pm)
    session = tm.get_session("proj-a")
    assert session is not None
    assert session.active_session_id is None


def test_get_session_empty_session_log(mock_pm):
    """Empty session log should not set active_session_id."""
    tm = TaskManager(project_manager=mock_pm)
    session = tm.get_session("proj-a")
    assert session is not None
    assert session.active_session_id is None


def test_get_session_cached_skips_restore(mock_pm):
    """Once a session is cached, get_session should not re-read the log."""
    data_dir = mock_pm.project_dir("proj-a")
    tm = TaskManager(project_manager=mock_pm)

    session = tm.get_session("proj-a")
    assert session is not None
    assert session.active_session_id is None

    sl = SessionLog(data_dir / "sessions.jsonl")
    sl.append(SessionRecord(
        session_id="sess-late",
        project_name="proj-a",
        status="active",
    ))

    same_session = tm.get_session("proj-a")
    assert same_session is session
    assert same_session.active_session_id is None


# ── Restored session → send task (end-to-end) ─────────────────────


@pytest.mark.asyncio
@patch("chatcc.claude.task_manager.ProjectSession")
async def test_restored_session_sends_task_with_resume(MockSession, mock_pm):
    """End-to-end: restore session_id from JSONL → submit task →
    ensure_connected builds options with resume → query succeeds."""
    data_dir = mock_pm.project_dir("proj-a")
    sl = SessionLog(data_dir / "sessions.jsonl")
    sl.append(SessionRecord(
        session_id="restored-sess-id",
        project_name="proj-a",
        task_ids=["old-task"],
        total_cost_usd=0.05,
        status="active",
    ))

    mock_client = AsyncMock()
    mock_client.query = AsyncMock()

    mock_session = AsyncMock()
    mock_session.project = mock_pm.get_project("proj-a")
    mock_session.task_state = TaskState.IDLE
    mock_session.active_session_id = None
    mock_session.client = None
    mock_session.ensure_connected = AsyncMock(return_value=mock_client)
    mock_session.consume_response = AsyncMock(
        return_value={"session_id": "restored-sess-id", "cost": 0.03}
    )
    MockSession.return_value = mock_session

    notified: list[object] = []

    async def on_notify(_proj: str, msg: object) -> None:
        notified.append(msg)

    tm = TaskManager(project_manager=mock_pm, on_notify=on_notify)

    session = tm.get_session("proj-a")
    assert session is not None
    assert session.active_session_id == "restored-sess-id"

    await tm.submit_task("proj-a", "continue previous work")
    await asyncio.sleep(0.3)

    mock_client.query.assert_awaited_once_with("continue previous work")
    mock_session.consume_response.assert_awaited_once()
    assert mock_session.task_state == TaskState.COMPLETED
    assert any("任务完成" in str(n) for n in notified)

    task_log = tm.get_task_log("proj-a")
    records = task_log.latest(1) if task_log else []
    assert len(records) == 1
    assert records[0].status == "completed"
    assert records[0].session_id == "restored-sess-id"


@pytest.mark.asyncio
@patch("chatcc.claude.task_manager.ProjectSession")
async def test_fresh_session_no_resume(MockSession, mock_pm):
    """When no session is restored, ensure_connected is called with
    active_session_id=None (no resume parameter)."""
    mock_client = AsyncMock()
    mock_client.query = AsyncMock()

    mock_session = AsyncMock()
    mock_session.project = mock_pm.get_project("proj-a")
    mock_session.task_state = TaskState.IDLE
    mock_session.active_session_id = None
    mock_session.client = None
    mock_session.ensure_connected = AsyncMock(return_value=mock_client)
    mock_session.consume_response = AsyncMock(
        return_value={"session_id": "brand-new-sess", "cost": 0.01}
    )
    MockSession.return_value = mock_session

    tm = TaskManager(project_manager=mock_pm)
    session = tm.get_session("proj-a")
    assert session is not None
    assert session.active_session_id is None

    await tm.submit_task("proj-a", "start fresh")
    await asyncio.sleep(0.3)

    mock_client.query.assert_awaited_once_with("start fresh")
    assert mock_session.task_state == TaskState.COMPLETED


# ── ProcessError recovery ─────────────────────────────────────────


@pytest.mark.asyncio
@patch("chatcc.claude.task_manager.ProjectSession")
async def test_process_error_retries_with_fresh_session(MockSession, mock_pm):
    """When a resumed session hits a ProcessError (dead Claude Code process),
    _run_task_item should disconnect, clear the session ID, and retry."""
    mock_client_bad = AsyncMock()
    mock_client_bad.query = AsyncMock(
        side_effect=RuntimeError("Cannot write to terminated process (exit code: 1)")
    )
    mock_client_good = AsyncMock()
    mock_client_good.query = AsyncMock()

    mock_session = AsyncMock()
    mock_session.project = mock_pm.get_project("proj-a")
    mock_session.task_state = TaskState.IDLE
    mock_session.active_session_id = "old-sess"
    mock_session.client = None
    mock_session.disconnect = AsyncMock()

    call_count = 0

    async def fake_ensure_connected():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return mock_client_bad
        return mock_client_good

    mock_session.ensure_connected = fake_ensure_connected
    mock_session.consume_response = AsyncMock(
        return_value={"session_id": "new-sess", "cost": 0.02}
    )
    MockSession.return_value = mock_session

    notified: list[object] = []

    async def on_notify(_proj: str, msg: object) -> None:
        notified.append(msg)

    tm = TaskManager(project_manager=mock_pm, on_notify=on_notify)
    await tm.submit_task("proj-a", "do something")
    await asyncio.sleep(0.3)

    assert mock_session.task_state == TaskState.COMPLETED
    assert any("重试成功" in str(n) for n in notified)
    assert mock_session.disconnect.await_count >= 1


@pytest.mark.asyncio
@patch("chatcc.claude.task_manager.ProjectSession")
async def test_process_error_retry_also_fails(MockSession, mock_pm):
    """If the retry after process error also fails, the task is marked failed."""
    mock_client = AsyncMock()
    mock_client.query = AsyncMock(
        side_effect=RuntimeError("Cannot write to terminated process (exit code: 1)")
    )

    mock_session = AsyncMock()
    mock_session.project = mock_pm.get_project("proj-a")
    mock_session.task_state = TaskState.IDLE
    mock_session.active_session_id = "old-sess"
    mock_session.client = None
    mock_session.disconnect = AsyncMock()
    mock_session.ensure_connected = AsyncMock(return_value=mock_client)
    MockSession.return_value = mock_session

    notified: list[object] = []

    async def on_notify(_proj: str, msg: object) -> None:
        notified.append(msg)

    tm = TaskManager(project_manager=mock_pm, on_notify=on_notify)
    await tm.submit_task("proj-a", "do something")
    await asyncio.sleep(0.3)

    assert mock_session.task_state == TaskState.FAILED
    assert any("重试失败" in str(n) for n in notified)


# ── Session compression on rotate ─────────────────────────────────


@pytest.mark.asyncio
@patch("chatcc.claude.task_manager.ProjectSession")
async def test_pending_summary_injected_into_prompt(MockSession, mock_pm):
    """When a pending summary exists for a project, the first task prompt
    should be prefixed with the compressed context."""
    mock_client = AsyncMock()
    mock_client.query = AsyncMock()

    mock_session = AsyncMock()
    mock_session.project = mock_pm.get_project("proj-a")
    mock_session.task_state = TaskState.IDLE
    mock_session.active_session_id = None
    mock_session.client = None
    mock_session.ensure_connected = AsyncMock(return_value=mock_client)
    mock_session.consume_response = AsyncMock(
        return_value={"session_id": "new-sess", "cost": 0.01}
    )
    MockSession.return_value = mock_session

    tm = TaskManager(project_manager=mock_pm)
    tm._pending_summaries["proj-a"] = "之前完成了JWT认证"

    await tm.submit_task("proj-a", "继续实现权限系统")
    await asyncio.sleep(0.3)

    call_args = mock_client.query.call_args
    prompt_sent = call_args[0][0] if call_args[0] else call_args[1].get("prompt", "")
    assert "之前完成了JWT认证" in prompt_sent
    assert "继续实现权限系统" in prompt_sent
    assert "proj-a" not in tm._pending_summaries


@pytest.mark.asyncio
@patch("chatcc.claude.task_manager.ProjectSession")
async def test_no_summary_no_prefix(MockSession, mock_pm):
    """Without a pending summary, the prompt is sent as-is."""
    mock_client = AsyncMock()
    mock_client.query = AsyncMock()

    mock_session = AsyncMock()
    mock_session.project = mock_pm.get_project("proj-a")
    mock_session.task_state = TaskState.IDLE
    mock_session.active_session_id = None
    mock_session.client = None
    mock_session.ensure_connected = AsyncMock(return_value=mock_client)
    mock_session.consume_response = AsyncMock(
        return_value={"session_id": "s1", "cost": 0.01}
    )
    MockSession.return_value = mock_session

    tm = TaskManager(project_manager=mock_pm)
    await tm.submit_task("proj-a", "build feature")
    await asyncio.sleep(0.3)

    mock_client.query.assert_awaited_once_with("build feature")


@pytest.mark.asyncio
@patch("chatcc.claude.task_manager.compress_session", new_callable=AsyncMock)
@patch("chatcc.claude.task_manager.ProjectSession")
async def test_rotate_with_compress(MockSession, mock_compress, mock_pm):
    """When compress_on_rotate is True, rotation should compress and store summary."""
    mock_compress.return_value = "完成了用户认证"

    mock_session = AsyncMock()
    mock_session.project = mock_pm.get_project("proj-a")
    mock_session.task_state = TaskState.IDLE
    mock_session.active_session_id = "old-sess"
    mock_session.disconnect = AsyncMock()
    MockSession.return_value = mock_session

    policy = SessionPolicyConfig(compress_on_rotate=True, max_tasks_per_session=1)
    tm = TaskManager(project_manager=mock_pm, session_policy=policy)
    tm._sessions["proj-a"] = mock_session

    sl = tm.get_session_log("proj-a")
    sl.append(SessionRecord(
        session_id="old-sess", project_name="proj-a",
        task_ids=["t1"], status="active",
    ))

    await tm._rotate_session("proj-a")

    mock_compress.assert_awaited_once_with(
        "old-sess", mock_session.project.path, model=mock_session.project.config.model,
    )
    assert tm._pending_summaries.get("proj-a") == "完成了用户认证"


@pytest.mark.asyncio
@patch("chatcc.claude.task_manager.compress_session", new_callable=AsyncMock)
@patch("chatcc.claude.task_manager.ProjectSession")
async def test_rotate_compress_disabled(MockSession, mock_compress, mock_pm):
    """When compress_on_rotate is False (default), no compression happens."""
    mock_session = AsyncMock()
    mock_session.project = mock_pm.get_project("proj-a")
    mock_session.task_state = TaskState.IDLE
    mock_session.active_session_id = "old-sess"
    mock_session.disconnect = AsyncMock()
    MockSession.return_value = mock_session

    policy = SessionPolicyConfig(compress_on_rotate=False)
    tm = TaskManager(project_manager=mock_pm, session_policy=policy)
    tm._sessions["proj-a"] = mock_session

    sl = tm.get_session_log("proj-a")
    sl.append(SessionRecord(
        session_id="old-sess", project_name="proj-a", status="active",
    ))

    await tm._rotate_session("proj-a")

    mock_compress.assert_not_awaited()
    assert "proj-a" not in tm._pending_summaries


@pytest.mark.asyncio
@patch("chatcc.claude.task_manager.compress_session", new_callable=AsyncMock)
@patch("chatcc.claude.task_manager.ProjectSession")
async def test_rotate_compress_failure_degrades(MockSession, mock_compress, mock_pm):
    """Compression failure should not block rotation."""
    mock_compress.return_value = None

    mock_session = AsyncMock()
    mock_session.project = mock_pm.get_project("proj-a")
    mock_session.task_state = TaskState.IDLE
    mock_session.active_session_id = "old-sess"
    mock_session.disconnect = AsyncMock()
    MockSession.return_value = mock_session

    policy = SessionPolicyConfig(compress_on_rotate=True, max_tasks_per_session=1)
    tm = TaskManager(project_manager=mock_pm, session_policy=policy)
    tm._sessions["proj-a"] = mock_session

    sl = tm.get_session_log("proj-a")
    sl.append(SessionRecord(
        session_id="old-sess", project_name="proj-a", status="active",
    ))

    await tm._rotate_session("proj-a")

    mock_session.disconnect.assert_awaited()
    assert mock_session.active_session_id is None
    assert "proj-a" not in tm._pending_summaries


# ── Restore pending summary on restart ─────────────────────────────


def test_restore_recovers_pending_summary(mock_pm):
    """On restart, if the most recent closed session has a summary,
    it should be loaded into _pending_summaries."""
    data_dir = mock_pm.project_dir("proj-a")
    sl = SessionLog(data_dir / "sessions.jsonl")
    sl.append(SessionRecord(
        session_id="old-sess",
        project_name="proj-a",
        status="closed",
        summary="完成了数据库迁移",
    ))

    policy = SessionPolicyConfig(compress_on_rotate=True)
    tm = TaskManager(project_manager=mock_pm, session_policy=policy)
    tm.get_session("proj-a")

    assert tm._pending_summaries.get("proj-a") == "完成了数据库迁移"


def test_restore_no_summary_when_disabled(mock_pm):
    """When compress_on_rotate is off, don't restore summaries."""
    data_dir = mock_pm.project_dir("proj-a")
    sl = SessionLog(data_dir / "sessions.jsonl")
    sl.append(SessionRecord(
        session_id="old-sess",
        project_name="proj-a",
        status="closed",
        summary="完成了数据库迁移",
    ))

    policy = SessionPolicyConfig(compress_on_rotate=False)
    tm = TaskManager(project_manager=mock_pm, session_policy=policy)
    tm.get_session("proj-a")

    assert "proj-a" not in tm._pending_summaries


def test_restore_no_summary_when_active_session_exists(mock_pm):
    """If there's an active session (not yet rotated), don't load old summary."""
    data_dir = mock_pm.project_dir("proj-a")
    sl = SessionLog(data_dir / "sessions.jsonl")
    sl.append(SessionRecord(
        session_id="old-sess", project_name="proj-a",
        status="closed", summary="旧摘要",
    ))
    sl.append(SessionRecord(
        session_id="current-sess", project_name="proj-a",
        status="active",
    ))

    policy = SessionPolicyConfig(compress_on_rotate=True)
    tm = TaskManager(project_manager=mock_pm, session_policy=policy)
    tm.get_session("proj-a")

    assert "proj-a" not in tm._pending_summaries
