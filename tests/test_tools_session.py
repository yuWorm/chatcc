from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from chatcc.agent.dispatcher import AgentDeps, Dispatcher
from chatcc.claude.session import TaskState
from chatcc.project.manager import ProjectManager
from chatcc.project.models import SubmitResult


@pytest.fixture
def dispatcher() -> Dispatcher:
    return Dispatcher(
        provider_name="test",
        model_id=TestModel(),
        persona="default",
    )


def _ctx(deps: AgentDeps) -> RunContext[AgentDeps]:
    return RunContext(deps=deps, model=TestModel(), usage=RunUsage())


def test_session_tools_registered(dispatcher: Dispatcher) -> None:
    tools = list(dispatcher.agent._function_toolset.tools.keys())
    assert "send_to_claude" in tools
    assert "get_task_status" in tools
    assert "interrupt_task" in tools
    assert "new_session" in tools
    assert "get_session_info" in tools


@pytest.mark.asyncio
async def test_send_to_claude_valid_project(tmp_path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("p1", "/tmp/p1")
    tm = MagicMock()
    tm.submit_task = AsyncMock(return_value=SubmitResult(
        status="submitted", message="任务已提交到项目 'p1'",
    ))
    deps = AgentDeps(project_manager=pm, task_manager=tm)
    fn = dispatcher.agent._function_toolset.tools["send_to_claude"].function
    out = await fn(_ctx(deps), "do the thing", "p1")
    assert out == "任务已提交到项目 'p1'"
    tm.submit_task.assert_awaited_once_with("p1", "do the thing")


@pytest.mark.asyncio
async def test_send_to_claude_no_task_manager(tmp_path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("p1", "/x")
    fn = dispatcher.agent._function_toolset.tools["send_to_claude"].function
    out = await fn(_ctx(AgentDeps(project_manager=pm)), "hi", "")
    assert "任务管理器未初始化" in out


@pytest.mark.asyncio
async def test_send_to_claude_no_project_manager(dispatcher: Dispatcher) -> None:
    tm = MagicMock()
    fn = dispatcher.agent._function_toolset.tools["send_to_claude"].function
    out = await fn(_ctx(AgentDeps(task_manager=tm)), "hi", "")
    assert "项目管理器未初始化" in out


@pytest.mark.asyncio
async def test_send_to_claude_no_default_project(
    tmp_path, dispatcher: Dispatcher
) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    tm = MagicMock()
    fn = dispatcher.agent._function_toolset.tools["send_to_claude"].function
    out = await fn(_ctx(AgentDeps(project_manager=pm, task_manager=tm)), "x", "")
    assert "未设置默认项目" in out


@pytest.mark.asyncio
async def test_send_to_claude_unknown_project(tmp_path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    tm = MagicMock()
    fn = dispatcher.agent._function_toolset.tools["send_to_claude"].function
    out = await fn(_ctx(AgentDeps(project_manager=pm, task_manager=tm)), "x", "nope")
    assert "未找到目标项目" in out


def test_get_task_status_all_empty(tmp_path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    tm = MagicMock()
    tm.get_all_status = MagicMock(return_value={})
    fn = dispatcher.agent._function_toolset.tools["get_task_status"].function
    out = fn(_ctx(AgentDeps(project_manager=pm, task_manager=tm)), "")
    assert out == "暂无活跃的 Claude Code 会话"


def test_get_task_status_all_listing(tmp_path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    tm = MagicMock()
    tm.get_all_status = MagicMock(return_value={"a": "idle", "b": "running"})
    fn = dispatcher.agent._function_toolset.tools["get_task_status"].function
    out = fn(_ctx(AgentDeps(project_manager=pm, task_manager=tm)), "")
    assert "- a: idle" in out
    assert "- b: running" in out


def test_get_task_status_specific_project(tmp_path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("alpha", "/x")
    tm = MagicMock()
    tm.get_task_status = MagicMock(return_value="running")
    fn = dispatcher.agent._function_toolset.tools["get_task_status"].function
    out = fn(_ctx(AgentDeps(project_manager=pm, task_manager=tm)), "alpha")
    assert "[alpha]" in out
    assert "running" in out
    tm.get_task_status.assert_called_once_with("alpha")


def test_get_task_status_no_managers(dispatcher: Dispatcher) -> None:
    fn = dispatcher.agent._function_toolset.tools["get_task_status"].function
    out = fn(_ctx(AgentDeps()), "")
    assert "管理器未初始化" in out


def test_get_task_status_unknown_project(tmp_path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    tm = MagicMock()
    fn = dispatcher.agent._function_toolset.tools["get_task_status"].function
    out = fn(_ctx(AgentDeps(project_manager=pm, task_manager=tm)), "missing")
    assert "未找到目标项目" in out


@pytest.mark.asyncio
async def test_interrupt_task_calls_tm(tmp_path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("p1", "/z")
    tm = MagicMock()
    tm.interrupt_task = AsyncMock(return_value="已中断")
    fn = dispatcher.agent._function_toolset.tools["interrupt_task"].function
    out = await fn(_ctx(AgentDeps(project_manager=pm, task_manager=tm)), "")
    assert out == "已中断"
    tm.interrupt_task.assert_awaited_once_with("p1")


@pytest.mark.asyncio
async def test_interrupt_task_no_managers(dispatcher: Dispatcher) -> None:
    fn = dispatcher.agent._function_toolset.tools["interrupt_task"].function
    out = await fn(_ctx(AgentDeps()), "")
    assert "管理器未初始化" in out


@pytest.mark.asyncio
async def test_new_session_disconnects_and_resets(
    tmp_path, dispatcher: Dispatcher
) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("p1", "/q")
    session = MagicMock()
    session.disconnect = AsyncMock()
    session.active_session_id = "old-id"
    session.task_state = TaskState.RUNNING
    tm = MagicMock()
    tm.get_session = MagicMock(return_value=session)
    fn = dispatcher.agent._function_toolset.tools["new_session"].function
    out = await fn(_ctx(AgentDeps(project_manager=pm, task_manager=tm)), "p1")
    assert "会话已重置" in out
    assert "p1" in out
    assert "old-id" in out  # old session_id mentioned
    tm.close_session.assert_called_once_with("p1")
    session.disconnect.assert_awaited_once()
    assert session.active_session_id is None
    assert session.task_state == TaskState.IDLE


@pytest.mark.asyncio
async def test_new_session_no_session_record(tmp_path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("p1", "/q")
    tm = MagicMock()
    tm.get_session = MagicMock(return_value=None)
    fn = dispatcher.agent._function_toolset.tools["new_session"].function
    out = await fn(_ctx(AgentDeps(project_manager=pm, task_manager=tm)), "p1")
    assert "不存在" in out


@pytest.mark.asyncio
async def test_new_session_no_managers(dispatcher: Dispatcher) -> None:
    fn = dispatcher.agent._function_toolset.tools["new_session"].function
    out = await fn(_ctx(AgentDeps()), "")
    assert "管理器未初始化" in out


# --- get_session_info ---


def test_get_session_info_no_managers(dispatcher: Dispatcher) -> None:
    fn = dispatcher.agent._function_toolset.tools["get_session_info"].function
    out = fn(_ctx(AgentDeps()), "")
    assert "管理器未初始化" in out


def test_get_session_info_no_sessions(tmp_path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("p1", "/x")
    from chatcc.project.session_log import SessionLog

    tm = MagicMock()
    tm.get_session_log = MagicMock(return_value=SessionLog(tmp_path / "p1" / "sessions.jsonl"))
    fn = dispatcher.agent._function_toolset.tools["get_session_info"].function
    out = fn(_ctx(AgentDeps(project_manager=pm, task_manager=tm)), "p1")
    assert "暂无会话记录" in out


def test_get_session_info_with_active_session(tmp_path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("p1", "/x")
    from chatcc.project.models import SessionRecord
    from chatcc.project.session_log import SessionLog

    sl = SessionLog(tmp_path / "p1" / "sessions.jsonl")
    sl.append(SessionRecord(
        session_id="sess-abc123",
        project_name="p1",
        task_ids=["t1", "t2"],
        total_cost_usd=0.05,
    ))
    tm = MagicMock()
    tm.get_session_log = MagicMock(return_value=sl)
    fn = dispatcher.agent._function_toolset.tools["get_session_info"].function
    out = fn(_ctx(AgentDeps(project_manager=pm, task_manager=tm)), "p1")
    assert "sess-abc" in out
    assert "任务数: 2" in out
    assert "$0.0500" in out


def test_get_session_info_unknown_project(tmp_path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    tm = MagicMock()
    fn = dispatcher.agent._function_toolset.tools["get_session_info"].function
    out = fn(_ctx(AgentDeps(project_manager=pm, task_manager=tm)), "nope")
    assert "未找到目标项目" in out


# --- resume_session ---


def test_resume_session_registered(dispatcher: Dispatcher) -> None:
    tools = list(dispatcher.agent._function_toolset.tools.keys())
    assert "resume_session" in tools
    assert "list_claude_sessions" in tools


@pytest.mark.asyncio
async def test_resume_session_switches_session(tmp_path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("p1", str(tmp_path / "proj1"))
    session = MagicMock()
    session.disconnect = AsyncMock()
    session.active_session_id = "old-sess"
    session.task_state = TaskState.IDLE
    tm = MagicMock()
    tm.get_session = MagicMock(return_value=session)
    fn = dispatcher.agent._function_toolset.tools["resume_session"].function
    out = await fn(
        _ctx(AgentDeps(project_manager=pm, task_manager=tm)),
        "new-sess-id",
        "p1",
    )
    assert "new-sess" in out
    assert "old-sess" in out
    assert session.active_session_id == "new-sess-id"
    assert session.task_state == TaskState.IDLE
    tm.close_session.assert_called_once_with("p1")
    session.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_resume_session_same_id(tmp_path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("p1", str(tmp_path / "proj1"))
    session = MagicMock()
    session.active_session_id = "same-id"
    session.task_state = TaskState.IDLE
    tm = MagicMock()
    tm.get_session = MagicMock(return_value=session)
    fn = dispatcher.agent._function_toolset.tools["resume_session"].function
    out = await fn(
        _ctx(AgentDeps(project_manager=pm, task_manager=tm)),
        "same-id",
        "p1",
    )
    assert "已在该会话中" in out


@pytest.mark.asyncio
async def test_resume_session_rejects_while_running(
    tmp_path, dispatcher: Dispatcher
) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("p1", str(tmp_path / "proj1"))
    session = MagicMock()
    session.active_session_id = "old"
    session.task_state = TaskState.RUNNING
    tm = MagicMock()
    tm.get_session = MagicMock(return_value=session)
    fn = dispatcher.agent._function_toolset.tools["resume_session"].function
    out = await fn(
        _ctx(AgentDeps(project_manager=pm, task_manager=tm)),
        "new-id",
        "p1",
    )
    assert "正在执行" in out


@pytest.mark.asyncio
async def test_resume_session_no_managers(dispatcher: Dispatcher) -> None:
    fn = dispatcher.agent._function_toolset.tools["resume_session"].function
    out = await fn(_ctx(AgentDeps()), "sid", "")
    assert "管理器未初始化" in out


@pytest.mark.asyncio
async def test_resume_session_from_none(tmp_path, dispatcher: Dispatcher) -> None:
    """Resume when there was no previous session (active_session_id is None)."""
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("p1", str(tmp_path / "proj1"))
    session = MagicMock()
    session.disconnect = AsyncMock()
    session.active_session_id = None
    session.task_state = TaskState.IDLE
    tm = MagicMock()
    tm.get_session = MagicMock(return_value=session)
    fn = dispatcher.agent._function_toolset.tools["resume_session"].function
    out = await fn(
        _ctx(AgentDeps(project_manager=pm, task_manager=tm)),
        "target-sess",
        "p1",
    )
    assert "target-s" in out
    assert session.active_session_id == "target-sess"
    tm.close_session.assert_not_called()
