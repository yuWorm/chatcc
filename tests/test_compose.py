import asyncio

from chatcc.approval.table import PendingApproval
from chatcc.channel.compose import (
    compose_conflict_choice,
    compose_confirmation,
    compose_pending_list,
    compose_session_rotated,
)
from chatcc.channel.message import ActionGroup, ProgressElement, TextElement


def test_compose_conflict_choice():
    rich = compose_conflict_choice("myapp", "build feature X", 5)
    assert rich.project_tag == "myapp"
    texts = [e for e in rich.elements if isinstance(e, TextElement)]
    assert any("myapp" in t.content for t in texts)
    assert any("build feature X" in t.content for t in texts)
    groups = [e for e in rich.elements if isinstance(e, ActionGroup)]
    assert len(groups) == 1
    buttons = groups[0].buttons
    assert len(buttons) == 3
    commands = [b.command for b in buttons]
    assert "/resolve 5 queue" in commands
    assert "/resolve 5 interrupt" in commands
    assert "/resolve 5 cancel" in commands


def test_compose_confirmation():
    rich = compose_confirmation("myapp", "确定要中断当前任务？", 7)
    assert rich.project_tag == "myapp"
    groups = [e for e in rich.elements if isinstance(e, ActionGroup)]
    assert len(groups) == 1
    buttons = groups[0].buttons
    assert len(buttons) == 2
    commands = [b.command for b in buttons]
    assert "/resolve 7 approve" in commands
    assert "/resolve 7 deny" in commands


def test_compose_pending_list_with_choices():
    loop = asyncio.new_event_loop()
    items = [
        PendingApproval(
            id=1,
            project="a",
            tool_name="Bash",
            input_summary="rm -rf /",
            future=loop.create_future(),
        ),
        PendingApproval(
            id=2,
            project="b",
            tool_name="send_to_claude",
            input_summary="项目正在执行任务",
            future=loop.create_future(),
            choices=[("排队", "queue"), ("打断", "interrupt"), ("取消", "cancel")],
        ),
    ]
    rich = compose_pending_list(items)
    groups = [e for e in rich.elements if isinstance(e, ActionGroup)]
    assert len(groups) == 2
    # binary item has /y /n
    assert any("/y 1" in b.command for b in groups[0].buttons)
    # choice item has /resolve
    assert any("/resolve 2" in b.command for b in groups[1].buttons)
    loop.close()


def test_compose_pending_list_empty():
    rich = compose_pending_list([])
    texts = [e for e in rich.elements if isinstance(e, TextElement)]
    assert any("暂无" in t.content for t in texts)


def test_compose_session_rotated_compressing():
    rich = compose_session_rotated("myapp", "compressing")
    elems = [e for e in rich.elements if isinstance(e, ProgressElement)]
    assert len(elems) == 1
    assert "压缩" in elems[0].description
