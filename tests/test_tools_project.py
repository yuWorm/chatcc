from pathlib import Path

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


def test_project_tools_registered(dispatcher: Dispatcher) -> None:
    names = set(dispatcher.agent._function_toolset.tools.keys())
    assert names == {
        "create_project",
        "delete_project",
        "get_project_info",
        "list_projects",
        "switch_project",
    }


def test_create_project_success(tmp_path: Path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    deps = AgentDeps(project_manager=pm)
    fn = dispatcher.agent._function_toolset.tools["create_project"].function
    out = fn(_ctx(deps), "p1", "/tmp/foo")
    assert "创建成功" in out
    assert "p1" in out
    assert pm.get_project("p1") is not None


def test_create_project_duplicate(tmp_path: Path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("p1", "/a")
    deps = AgentDeps(project_manager=pm)
    fn = dispatcher.agent._function_toolset.tools["create_project"].function
    out = fn(_ctx(deps), "p1", "/b")
    assert "创建失败" in out


def test_create_project_no_pm(dispatcher: Dispatcher) -> None:
    fn = dispatcher.agent._function_toolset.tools["create_project"].function
    out = fn(_ctx(AgentDeps()), "x", "/y")
    assert "未初始化" in out


def test_list_projects_empty(tmp_path: Path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    fn = dispatcher.agent._function_toolset.tools["list_projects"].function
    out = fn(_ctx(AgentDeps(project_manager=pm)))
    assert out == "暂无项目"


def test_list_projects_with_default(tmp_path: Path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("a", "/x")
    pm.create_project("b", "/y")
    pm.switch_default("b")
    fn = dispatcher.agent._function_toolset.tools["list_projects"].function
    out = fn(_ctx(AgentDeps(project_manager=pm)))
    assert "⭐" in out
    assert "b" in out


def test_switch_project(tmp_path: Path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("a", "/x")
    pm.create_project("b", "/y")
    fn = dispatcher.agent._function_toolset.tools["switch_project"].function
    out = fn(_ctx(AgentDeps(project_manager=pm)), "b")
    assert "已切换" in out
    assert pm.default_project and pm.default_project.name == "b"


def test_get_project_info_default(tmp_path: Path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("only", "/z")
    fn = dispatcher.agent._function_toolset.tools["get_project_info"].function
    out = fn(_ctx(AgentDeps(project_manager=pm)), "")
    assert "名称: only" in out
    assert "路径: /z" in out


def test_get_project_info_by_name(tmp_path: Path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("x", "/p")
    fn = dispatcher.agent._function_toolset.tools["get_project_info"].function
    out = fn(_ctx(AgentDeps(project_manager=pm)), "x")
    assert "名称: x" in out


def test_delete_project(tmp_path: Path, dispatcher: Dispatcher) -> None:
    pm = ProjectManager(data_dir=tmp_path)
    pm.create_project("gone", "/g")
    fn = dispatcher.agent._function_toolset.tools["delete_project"].function
    out = fn(_ctx(AgentDeps(project_manager=pm)), "gone")
    assert "已归档" in out
    assert pm.get_project("gone") is None
