from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from chatcc.agent.dispatcher import AgentDeps, Dispatcher
from chatcc.project.manager import ProjectManager


@pytest.fixture
def dispatcher() -> Dispatcher:
    return Dispatcher(
        provider_name="test",
        model_id=TestModel(),
        persona="default",
    )


def _ctx(deps: AgentDeps) -> RunContext[AgentDeps]:
    return RunContext(deps=deps, model=TestModel(), usage=RunUsage())


def test_install_tools_registered(dispatcher: Dispatcher) -> None:
    tools = list(dispatcher.agent._function_toolset.tools.keys())
    assert "install_skill" in tools
    assert "install_mcp" in tools


@pytest.mark.asyncio
async def test_install_skill_success(tmp_path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("p1", "/tmp/p1")
    tm = MagicMock()
    tm.submit_task = AsyncMock(return_value="任务已提交到项目 'p1'")
    deps = AgentDeps(project_manager=pm, task_manager=tm)
    fn = dispatcher.agent._function_toolset.tools["install_skill"].function
    url = "https://example.com/skill"
    out = await fn(_ctx(deps), url, "")
    assert url in out
    assert "p1" in out
    assert "安装指令" in out
    tm.submit_task.assert_awaited_once_with("p1", f"请安装以下 skill: {url}")


@pytest.mark.asyncio
async def test_install_skill_by_project_name(tmp_path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("alpha", "/x")
    pm.create_project("beta", "/y")
    tm = MagicMock()
    tm.submit_task = AsyncMock(return_value="任务已提交到项目 'beta'")
    fn = dispatcher.agent._function_toolset.tools["install_skill"].function
    await fn(_ctx(AgentDeps(project_manager=pm, task_manager=tm)), "u", "beta")
    tm.submit_task.assert_awaited_once_with("beta", "请安装以下 skill: u")


@pytest.mark.asyncio
async def test_install_skill_submit_error_passes_through(
    tmp_path, dispatcher: Dispatcher
) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("p1", "/z")
    tm = MagicMock()
    err = "错误: 项目 'p1' 正在执行任务，请等待完成或使用 /stop"
    tm.submit_task = AsyncMock(return_value=err)
    fn = dispatcher.agent._function_toolset.tools["install_skill"].function
    out = await fn(_ctx(AgentDeps(project_manager=pm, task_manager=tm)), "u", "")
    assert out == err


@pytest.mark.asyncio
async def test_install_skill_no_managers(dispatcher: Dispatcher) -> None:
    fn = dispatcher.agent._function_toolset.tools["install_skill"].function
    out = await fn(_ctx(AgentDeps()), "u", "")
    assert "管理器未初始化" in out


@pytest.mark.asyncio
async def test_install_skill_no_default_project(
    tmp_path, dispatcher: Dispatcher
) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    tm = MagicMock()
    fn = dispatcher.agent._function_toolset.tools["install_skill"].function
    out = await fn(_ctx(AgentDeps(project_manager=pm, task_manager=tm)), "u", "")
    assert "未设置默认项目" in out


@pytest.mark.asyncio
async def test_install_skill_unknown_project(tmp_path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    tm = MagicMock()
    fn = dispatcher.agent._function_toolset.tools["install_skill"].function
    out = await fn(_ctx(AgentDeps(project_manager=pm, task_manager=tm)), "u", "nope")
    assert "未找到目标项目" in out


@pytest.mark.asyncio
async def test_install_mcp_success_no_args(tmp_path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("p1", "/tmp/p1")
    tm = MagicMock()
    tm.submit_task = AsyncMock(return_value="任务已提交到项目 'p1'")
    fn = dispatcher.agent._function_toolset.tools["install_mcp"].function
    out = await fn(_ctx(AgentDeps(project_manager=pm, task_manager=tm)), "srv", "npx foo", "")
    assert "srv" in out
    assert "p1" in out
    assert "MCP" in out or "配置指令" in out
    expected = "请配置以下 MCP server:\n名称: srv\n命令: npx foo"
    tm.submit_task.assert_awaited_once_with("p1", expected)


@pytest.mark.asyncio
async def test_install_mcp_success_with_args(tmp_path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("p1", "/q")
    tm = MagicMock()
    tm.submit_task = AsyncMock(return_value="任务已提交到项目 'p1'")
    fn = dispatcher.agent._function_toolset.tools["install_mcp"].function
    await fn(
        _ctx(AgentDeps(project_manager=pm, task_manager=tm)),
        "m",
        "cmd",
        "--port 9",
        "",
    )
    expected = (
        "请配置以下 MCP server:\n"
        "名称: m\n"
        "命令: cmd\n"
        "参数: --port 9"
    )
    tm.submit_task.assert_awaited_once_with("p1", expected)


@pytest.mark.asyncio
async def test_install_mcp_no_managers(dispatcher: Dispatcher) -> None:
    fn = dispatcher.agent._function_toolset.tools["install_mcp"].function
    out = await fn(_ctx(AgentDeps()), "n", "c", "", "")
    assert "管理器未初始化" in out


@pytest.mark.asyncio
async def test_install_mcp_no_default_project(
    tmp_path, dispatcher: Dispatcher
) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    tm = MagicMock()
    fn = dispatcher.agent._function_toolset.tools["install_mcp"].function
    out = await fn(_ctx(AgentDeps(project_manager=pm, task_manager=tm)), "n", "c", "", "")
    assert "未设置默认项目" in out


@pytest.mark.asyncio
async def test_install_mcp_unknown_project(tmp_path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    tm = MagicMock()
    fn = dispatcher.agent._function_toolset.tools["install_mcp"].function
    out = await fn(_ctx(AgentDeps(project_manager=pm, task_manager=tm)), "n", "c", "", "x")
    assert "未找到目标项目" in out
