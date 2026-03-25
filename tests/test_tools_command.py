from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from chatcc.agent.dispatcher import AgentDeps, Dispatcher
from chatcc.config import AppConfig, SecurityConfig
from chatcc.tools import command_tools
from chatcc.tools.command_tools import (
    is_project_within_workspace,
    run_command_in_workspace,
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


def test_is_project_within_workspace(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    inner = ws / "proj"
    inner.mkdir(parents=True)
    assert is_project_within_workspace(str(inner), str(ws))
    assert is_project_within_workspace(str(ws), str(ws))


def test_is_project_within_workspace_rejects_outside(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    assert not is_project_within_workspace(str(outside), str(ws))


async def test_run_command_echo(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    proj = ws / "p"
    proj.mkdir(parents=True)
    out = await run_command_in_workspace(
        str(proj), "echo hello", workspace_root=str(ws)
    )
    assert "hello" in out


async def test_run_command_stderr(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    proj = ws / "p"
    proj.mkdir(parents=True)
    out = await run_command_in_workspace(
        str(proj), 'echo errmsg 1>&2', workspace_root=str(ws)
    )
    assert "[stderr]" in out
    assert "errmsg" in out


async def test_run_command_nonzero_exit(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    proj = ws / "p"
    proj.mkdir(parents=True)
    out = await run_command_in_workspace(
        str(proj), "exit 7", workspace_root=str(ws)
    )
    assert "[exit code: 7]" in out


async def test_run_command_missing_dir(tmp_path: Path) -> None:
    out = await run_command_in_workspace(
        str(tmp_path / "nope"),
        "echo x",
        workspace_root=str(tmp_path),
    )
    assert "不存在" in out


async def test_run_command_outside_workspace(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    out = await run_command_in_workspace(
        str(outside),
        "echo x",
        workspace_root=str(ws),
    )
    assert "工作区" in out


async def test_run_command_timeout(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    proj = ws / "p"
    proj.mkdir(parents=True)
    out = await run_command_in_workspace(
        str(proj),
        "sleep 10",
        workspace_root=str(ws),
        timeout=0.25,
    )
    assert "超时" in out


async def test_run_command_truncates_long_output(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    proj = ws / "p"
    proj.mkdir(parents=True)
    out = await run_command_in_workspace(
        str(proj),
        "python -c \"print('x' * 5000)\"",
        workspace_root=str(ws),
    )
    assert len(out) <= 4000


async def test_execute_command_via_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = tmp_path / "ws"
    proj_dir = ws / "myproj"
    proj_dir.mkdir(parents=True)
    monkeypatch.setattr(
        command_tools,
        "load_config",
        lambda: AppConfig(security=SecurityConfig(workspace_root=str(ws))),
    )

    pm = MagicMock()
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


async def test_execute_command_no_default_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        command_tools,
        "load_config",
        lambda: AppConfig(security=SecurityConfig(workspace_root=str(tmp_path))),
    )
    pm = MagicMock()
    pm.default_project = None
    d = Dispatcher(provider_name="test", model_id=TestModel(), persona="default")
    fn = d.agent._function_toolset.tools["execute_command"].function
    out = await fn(_ctx(AgentDeps(project_manager=pm)), "echo x", "")
    assert "默认项目" in out


async def test_execute_command_named_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = tmp_path / "ws"
    proj_dir = ws / "p1"
    proj_dir.mkdir(parents=True)
    monkeypatch.setattr(
        command_tools,
        "load_config",
        lambda: AppConfig(security=SecurityConfig(workspace_root=str(ws))),
    )

    pm = MagicMock()
    p = MagicMock(path=str(proj_dir), name="p1")
    pm.get_project.return_value = p
    pm.default_project = None

    d = Dispatcher(provider_name="test", model_id=TestModel(), persona="default")
    fn = d.agent._function_toolset.tools["execute_command"].function
    out = await fn(_ctx(AgentDeps(project_manager=pm)), "echo hi", "p1")
    assert "hi" in out
    pm.get_project.assert_called_once_with("p1")


async def test_execute_command_unknown_named_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        command_tools,
        "load_config",
        lambda: AppConfig(security=SecurityConfig(workspace_root="/tmp")),
    )
    pm = MagicMock()
    pm.get_project.return_value = None
    d = Dispatcher(provider_name="test", model_id=TestModel(), persona="default")
    fn = d.agent._function_toolset.tools["execute_command"].function
    out = await fn(_ctx(AgentDeps(project_manager=pm)), "echo x", "missing")
    assert "未找到" in out
