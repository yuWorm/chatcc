from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from chatcc.agent.dispatcher import AgentDeps, Dispatcher
from chatcc.tools.command_tools import (
    is_path_within,
    run_command_in_project,
)


@pytest.fixture
def dispatcher() -> Dispatcher:
    return Dispatcher(
        provider_name="test",
        model_id=TestModel(),
        persona="default",
    )


def _ctx(deps: AgentDeps) -> RunContext[AgentDeps]:
    return RunContext(deps=deps, model=TestModel(), usage=RunUsage())


def test_command_tool_registered(dispatcher: Dispatcher) -> None:
    names = set(dispatcher.agent._function_toolset.tools.keys())
    assert "execute_command" in names


def test_is_path_within(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    inner = ws / "proj"
    inner.mkdir(parents=True)
    assert is_path_within(str(inner), str(ws))
    assert is_path_within(str(ws), str(ws))


def test_is_path_within_rejects_outside(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    assert not is_path_within(str(outside), str(ws))


async def test_run_command_echo(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    proj = ws / "p"
    proj.mkdir(parents=True)
    out = await run_command_in_project(
        str(proj), "echo hello", workspace=str(ws)
    )
    assert "hello" in out


async def test_run_command_stderr(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    proj = ws / "p"
    proj.mkdir(parents=True)
    out = await run_command_in_project(
        str(proj), 'echo errmsg 1>&2', workspace=str(ws)
    )
    assert "[stderr]" in out
    assert "errmsg" in out


async def test_run_command_nonzero_exit(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    proj = ws / "p"
    proj.mkdir(parents=True)
    out = await run_command_in_project(
        str(proj), "exit 7", workspace=str(ws)
    )
    assert "[exit code: 7]" in out


async def test_run_command_missing_dir(tmp_path: Path) -> None:
    out = await run_command_in_project(
        str(tmp_path / "nope"),
        "echo x",
        workspace=str(tmp_path),
    )
    assert "不存在" in out


async def test_run_command_outside_workspace(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    out = await run_command_in_project(
        str(outside),
        "echo x",
        workspace=str(ws),
    )
    assert "工作区" in out


async def test_run_command_timeout(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    proj = ws / "p"
    proj.mkdir(parents=True)
    out = await run_command_in_project(
        str(proj),
        "sleep 10",
        workspace=str(ws),
        timeout=0.25,
    )
    assert "超时" in out


async def test_run_command_truncates_long_output(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    proj = ws / "p"
    proj.mkdir(parents=True)
    out = await run_command_in_project(
        str(proj),
        "python -c \"print('x' * 5000)\"",
        workspace=str(ws),
    )
    assert len(out) <= 4000


async def test_execute_command_via_tool(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    proj_dir = ws / "myproj"
    proj_dir.mkdir(parents=True)

    pm = MagicMock()
    pm.workspace = Path(ws)
    proj = MagicMock()
    proj.path = str(proj_dir)
    proj.name = "myproj"
    pm.default_project = proj
    pm.get_project.return_value = proj

    d = Dispatcher(provider_name="test", model_id=TestModel(), persona="default")
    fn = d.agent._function_toolset.tools["execute_command"].function
    out = await fn(_ctx(AgentDeps(project_manager=pm)), 'printf "ab"')
    assert "ab" in out


async def test_execute_command_no_pm(dispatcher: Dispatcher) -> None:
    fn = dispatcher.agent._function_toolset.tools["execute_command"].function
    out = await fn(_ctx(AgentDeps()), "echo x")
    assert "未初始化" in out


async def test_execute_command_no_default_project(tmp_path: Path) -> None:
    pm = MagicMock()
    pm.workspace = tmp_path
    pm.default_project = None
    d = Dispatcher(provider_name="test", model_id=TestModel(), persona="default")
    fn = d.agent._function_toolset.tools["execute_command"].function
    out = await fn(_ctx(AgentDeps(project_manager=pm)), "echo x", "")
    assert "默认项目" in out


async def test_execute_command_named_project(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    proj_dir = ws / "p1"
    proj_dir.mkdir(parents=True)

    pm = MagicMock()
    pm.workspace = Path(ws)
    p = MagicMock(path=str(proj_dir), name="p1")
    pm.get_project.return_value = p
    pm.default_project = None

    d = Dispatcher(provider_name="test", model_id=TestModel(), persona="default")
    fn = d.agent._function_toolset.tools["execute_command"].function
    out = await fn(_ctx(AgentDeps(project_manager=pm)), "echo hi", "p1")
    assert "hi" in out
    pm.get_project.assert_called_once_with("p1")


async def test_execute_command_unknown_named_project() -> None:
    pm = MagicMock()
    pm.workspace = Path("/tmp")
    pm.get_project.return_value = None
    d = Dispatcher(provider_name="test", model_id=TestModel(), persona="default")
    fn = d.agent._function_toolset.tools["execute_command"].function
    out = await fn(_ctx(AgentDeps(project_manager=pm)), "echo x", "missing")
    assert "未找到" in out
