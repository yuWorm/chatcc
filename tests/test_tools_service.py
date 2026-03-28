from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from chatcc.agent.dispatcher import AgentDeps, Dispatcher
from chatcc.project.manager import ProjectManager
from chatcc.service.manager import RunningService


@pytest.fixture
def dispatcher() -> Dispatcher:
    return Dispatcher(
        provider_name="test",
        model_id=TestModel(),
        persona="default",
    )


def _ctx(deps: AgentDeps) -> RunContext[AgentDeps]:
    return RunContext(deps=deps, model=TestModel(), usage=RunUsage())


def test_service_tools_registered(dispatcher: Dispatcher) -> None:
    names = set(dispatcher.agent._function_toolset.tools.keys())
    assert "start_service" in names
    assert "stop_service" in names
    assert "service_status" in names
    assert "service_logs" in names


@pytest.mark.asyncio
async def test_start_service_success(tmp_path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("p1", "/tmp/p1")
    sm = MagicMock()
    running = MagicMock()
    running.pid = 4242
    sm.start = AsyncMock(return_value=running)
    deps = AgentDeps(project_manager=pm, service_manager=sm)
    fn = dispatcher.agent._function_toolset.tools["start_service"].function
    out = await fn(_ctx(deps), "svc", "echo hi", "")
    assert "已启动" in out
    assert "4242" in out
    sm.start.assert_awaited_once_with("p1", "svc", "echo hi", cwd="/tmp/p1")


@pytest.mark.asyncio
async def test_start_service_by_project_name(tmp_path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("alpha", "/x")
    pm.create_project("beta", "/y")
    sm = MagicMock()
    running = MagicMock()
    running.pid = 1
    sm.start = AsyncMock(return_value=running)
    deps = AgentDeps(project_manager=pm, service_manager=sm)
    fn = dispatcher.agent._function_toolset.tools["start_service"].function
    await fn(_ctx(deps), "n", "cmd", "beta")
    sm.start.assert_awaited_once_with("beta", "n", "cmd", cwd="/y")


@pytest.mark.asyncio
async def test_start_service_value_error(tmp_path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("p", "/z")
    sm = MagicMock()
    sm.start = AsyncMock(side_effect=ValueError("already running"))
    deps = AgentDeps(project_manager=pm, service_manager=sm)
    fn = dispatcher.agent._function_toolset.tools["start_service"].function
    out = await fn(_ctx(deps), "x", "y", "")
    assert "启动失败" in out
    assert "already running" in out


@pytest.mark.asyncio
async def test_start_service_no_service_manager(
    tmp_path, dispatcher: Dispatcher
) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("p", "/z")
    fn = dispatcher.agent._function_toolset.tools["start_service"].function
    out = await fn(_ctx(AgentDeps(project_manager=pm)), "a", "b", "")
    assert "服务管理器未初始化" in out


@pytest.mark.asyncio
async def test_start_service_no_project_manager(dispatcher: Dispatcher) -> None:
    sm = MagicMock()
    fn = dispatcher.agent._function_toolset.tools["start_service"].function
    out = await fn(_ctx(AgentDeps(service_manager=sm)), "a", "b", "")
    assert "项目管理器未初始化" in out


@pytest.mark.asyncio
async def test_start_service_no_default_project(
    tmp_path, dispatcher: Dispatcher
) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    sm = MagicMock()
    fn = dispatcher.agent._function_toolset.tools["start_service"].function
    out = await fn(_ctx(AgentDeps(project_manager=pm, service_manager=sm)), "a", "b", "")
    assert "未设置默认项目" in out


@pytest.mark.asyncio
async def test_stop_service_success(tmp_path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("p", "/q")
    sm = MagicMock()
    sm.stop = AsyncMock(return_value=True)
    deps = AgentDeps(project_manager=pm, service_manager=sm)
    fn = dispatcher.agent._function_toolset.tools["stop_service"].function
    out = await fn(_ctx(deps), "svc", "")
    assert "已停止" in out
    sm.stop.assert_awaited_once_with("p", "svc")


@pytest.mark.asyncio
async def test_stop_service_not_found(tmp_path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("p", "/q")
    sm = MagicMock()
    sm.stop = AsyncMock(return_value=False)
    fn = dispatcher.agent._function_toolset.tools["stop_service"].function
    out = await fn(_ctx(AgentDeps(project_manager=pm, service_manager=sm)), "missing", "")
    assert "未找到或已停止" in out


@pytest.mark.asyncio
async def test_stop_service_no_managers(dispatcher: Dispatcher) -> None:
    fn = dispatcher.agent._function_toolset.tools["stop_service"].function
    out = await fn(_ctx(AgentDeps()), "x", "")
    assert "管理器未初始化" in out


@pytest.mark.asyncio
async def test_stop_service_unknown_project(tmp_path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    sm = MagicMock()
    fn = dispatcher.agent._function_toolset.tools["stop_service"].function
    out = await fn(_ctx(AgentDeps(project_manager=pm, service_manager=sm)), "x", "nope")
    assert "未找到目标项目" in out


def test_service_status_empty(dispatcher: Dispatcher) -> None:
    sm = MagicMock()
    sm.status = MagicMock(return_value=[])
    fn = dispatcher.agent._function_toolset.tools["service_status"].function
    out = fn(_ctx(AgentDeps(service_manager=sm)))
    assert out == "暂无运行中的服务"


def test_service_status_listing(dispatcher: Dispatcher) -> None:
    sm = MagicMock()
    svc = RunningService(
        name="web",
        project="myproj",
        pid=99,
        command="npm run dev",
    )
    sm.status = MagicMock(return_value=[svc])
    fn = dispatcher.agent._function_toolset.tools["service_status"].function
    out = fn(_ctx(AgentDeps(service_manager=sm)), "")
    assert "[myproj]" in out
    assert "web" in out
    assert "99" in out
    assert "npm run dev" in out


def test_service_status_no_manager(dispatcher: Dispatcher) -> None:
    fn = dispatcher.agent._function_toolset.tools["service_status"].function
    out = fn(_ctx(AgentDeps()))
    assert "服务管理器未初始化" in out


@pytest.mark.asyncio
async def test_service_logs_success(tmp_path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("p", "/r")
    sm = MagicMock()
    sm.logs = AsyncMock(return_value="line1\nline2")
    fn = dispatcher.agent._function_toolset.tools["service_logs"].function
    out = await fn(_ctx(AgentDeps(project_manager=pm, service_manager=sm)), "svc", 10, "")
    assert out == "line1\nline2"
    sm.logs.assert_awaited_once_with("p", "svc", lines=10)


@pytest.mark.asyncio
async def test_service_logs_no_managers(dispatcher: Dispatcher) -> None:
    fn = dispatcher.agent._function_toolset.tools["service_logs"].function
    out = await fn(_ctx(AgentDeps()), "x", 5, "")
    assert "管理器未初始化" in out


def test_inspect_project_success(tmp_path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("web", str(tmp_path / "web"))
    (Path(pm.get_project("web").path) / "package.json").write_text(
        '{"name":"web","scripts":{"dev":"vite","build":"tsc"}}'
    )
    sm = MagicMock()
    from chatcc.service.detector import CommandEntry, ProjectProfile

    sm.detect_project = MagicMock(
        return_value=ProjectProfile(
            path=pm.get_project("web").path,
            project_type="node",
            readme_summary="A web app",
            available_commands=[
                CommandEntry(name="dev", command="npm run dev", source="package.json"),
                CommandEntry(name="build", command="npm run build", source="package.json"),
            ],
        )
    )
    deps = AgentDeps(project_manager=pm, service_manager=sm)
    fn = dispatcher.agent._function_toolset.tools["inspect_project"].function
    out = fn(_ctx(deps), "")
    assert "node" in out.lower() or "Node" in out
    assert "npm run dev" in out


def test_inspect_project_no_manager(dispatcher: Dispatcher) -> None:
    fn = dispatcher.agent._function_toolset.tools["inspect_project"].function
    out = fn(_ctx(AgentDeps()))
    assert "未初始化" in out
