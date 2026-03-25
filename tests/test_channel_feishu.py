import pytest
from chatcc.channel.feishu import FeishuChannel
from chatcc.channel.message import (
    RichMessage,
    TextElement,
    CodeElement,
    ActionGroup,
    ActionButton,
    ProgressElement,
    DividerElement,
)


@pytest.fixture
def channel():
    config = {
        "app_id": "test-app-id",
        "app_secret": "test-app-secret",
        "allowed_users": [],
    }
    return FeishuChannel(config)


def test_not_authenticated_without_credentials():
    ch = FeishuChannel({})
    assert ch.is_authenticated() is False


def test_authenticated_with_credentials(channel):
    assert channel.is_authenticated() is True


def test_render_text_only(channel):
    rich = RichMessage(elements=[TextElement(content="Hello")])
    card = channel.render(rich)
    assert isinstance(card, dict)
    assert card["msg_type"] == "interactive"
    assert "elements" in card["card"]


def test_render_with_project_tag(channel):
    rich = RichMessage(
        elements=[TextElement(content="test")],
        project_tag="myapp",
    )
    card = channel.render(rich)
    header = card["card"]["header"]
    assert "myapp" in header["title"]["content"]


def test_render_code_block(channel):
    rich = RichMessage(
        elements=[CodeElement(code="print('hello')", language="python")]
    )
    card = channel.render(rich)
    elements = card["card"]["elements"]
    code_found = any(
        "print('hello')" in el.get("text", {}).get("content", "")
        for el in elements
        if el.get("tag") == "div"
    )
    assert code_found


def test_render_action_buttons(channel):
    rich = RichMessage(
        elements=[
            ActionGroup(
                buttons=[
                    ActionButton(label="允许", command="/y 1"),
                    ActionButton(label="拒绝", command="/n 1"),
                ]
            ),
        ]
    )
    card = channel.render(rich)
    elements = card["card"]["elements"]
    action_found = any(el.get("tag") == "action" for el in elements)
    assert action_found


def test_render_full_approval_message(channel):
    rich = RichMessage(
        project_tag="myapp",
        elements=[
            TextElement(content="Claude Code 请求执行危险操作:"),
            CodeElement(code="rm -rf dist/", language="bash"),
            TextElement(content="工具: Bash | 请求 ID: #3"),
            DividerElement(),
            ActionGroup(
                buttons=[
                    ActionButton(label="✅ 允许", command="/y 3"),
                    ActionButton(label="❌ 拒绝", command="/n 3"),
                ]
            ),
        ],
    )
    card = channel.render(rich)
    assert card["msg_type"] == "interactive"
    assert "myapp" in card["card"]["header"]["title"]["content"]


def test_render_progress(channel):
    rich = RichMessage(
        elements=[ProgressElement(description="正在执行...", project="myapp")]
    )
    card = channel.render(rich)
    elements = card["card"]["elements"]
    assert any("正在执行" in str(el) for el in elements)


def test_render_divider(channel):
    rich = RichMessage(elements=[DividerElement()])
    card = channel.render(rich)
    elements = card["card"]["elements"]
    assert any(el.get("tag") == "hr" for el in elements)


def test_build_text_message(channel):
    payload = channel._build_send_payload("chat_123", "hello")
    assert payload["receive_id"] == "chat_123"
    assert payload["msg_type"] == "text"


def test_build_rich_message(channel):
    rich = RichMessage(elements=[TextElement(content="test")])
    payload = channel._build_send_payload("chat_123", rich)
    assert payload["msg_type"] == "interactive"


def test_user_allowed_empty_list(channel):
    assert channel._is_user_allowed("anyone") is True


def test_user_allowed_restricted():
    ch = FeishuChannel(
        {
            "app_id": "id",
            "app_secret": "secret",
            "allowed_users": ["ou_abc123"],
        }
    )
    assert ch._is_user_allowed("ou_abc123") is True
    assert ch._is_user_allowed("ou_other") is False
