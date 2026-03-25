from pydantic_ai.models.test import TestModel

from chatcc.agent.dispatcher import Dispatcher


def test_dispatcher_init():
    dispatcher = Dispatcher(
        provider_name="test",
        model_id=TestModel(),
        persona="default",
    )
    assert dispatcher.agent is not None


def test_dispatcher_has_tools():
    dispatcher = Dispatcher(
        provider_name="test",
        model_id=TestModel(),
        persona="default",
    )
    tool_names = list(dispatcher.agent._function_toolset.tools.keys())
    assert len(tool_names) > 0
