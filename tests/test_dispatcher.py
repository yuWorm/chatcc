from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from chatcc.agent.dispatcher import AgentDeps, Dispatcher


def test_dispatcher_init():
    dispatcher = Dispatcher(
        provider_name="test",
        model_id=TestModel(),
        persona="default",
    )
    assert dispatcher.agent is not None


def test_dispatcher_agent_configured():
    dispatcher = Dispatcher(
        provider_name="test",
        model_id=TestModel(),
        persona="default",
    )
    assert dispatcher.agent._model is not None
    assert dispatcher.agent.deps_type is AgentDeps
    assert dispatcher._build_instructions in dispatcher.agent._instructions
    tool_names = set(dispatcher.agent._function_toolset.tools.keys())
    assert tool_names == {
        "create_project",
        "delete_project",
        "execute_command",
        "get_project_info",
        "get_task_status",
        "install_mcp",
        "install_skill",
        "interrupt_task",
        "list_projects",
        "new_session",
        "send_to_claude",
        "service_logs",
        "service_status",
        "start_service",
        "stop_service",
        "switch_project",
    }


def test_build_instructions_with_empty_deps():
    dispatcher = Dispatcher(
        provider_name="default",
        model_id=TestModel(),
        persona="default",
    )
    model = TestModel()
    ctx = RunContext(deps=AgentDeps(), model=model, usage=RunUsage())
    text = dispatcher._build_instructions(ctx)
    assert "当前默认项目: 未设置" in text
    assert "活跃项目数: 0" in text
    assert "待确认操作: 0" in text
