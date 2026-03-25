from chatcc.agent.prompt import build_system_prompt


def test_build_system_prompt_contains_persona():
    prompt = build_system_prompt(
        persona_name="default",
        default_project="myapp",
        active_count=2,
        pending_count=1,
    )
    assert "ChatCC" in prompt
    assert "myapp" in prompt
    assert "2" in prompt


def test_build_system_prompt_no_project():
    prompt = build_system_prompt(
        persona_name="default",
        default_project=None,
        active_count=0,
        pending_count=0,
    )
    assert "未设置" in prompt
