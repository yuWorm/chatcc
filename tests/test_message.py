from chatcc.channel.message import (
    InboundMessage,
    OutboundMessage,
    RichMessage,
    TextElement,
    CodeElement,
    ActionButton,
    ActionGroup,
)


def test_inbound_message():
    msg = InboundMessage(sender_id="u1", content="hello", chat_id="c1")
    assert msg.sender_id == "u1"
    assert msg.media is None


def test_outbound_message_str():
    msg = OutboundMessage(chat_id="c1", content="hello")
    assert isinstance(msg.content, str)


def test_rich_message():
    rich = RichMessage(
        elements=[
            TextElement(content="请确认操作:"),
            CodeElement(code="rm -rf dist/", language="bash"),
            ActionGroup(buttons=[
                ActionButton(label="允许", command="/y 1"),
                ActionButton(label="拒绝", command="/n 1"),
            ]),
        ],
        project_tag="myapp",
    )
    assert len(rich.elements) == 3
    assert rich.project_tag == "myapp"


def test_outbound_message_rich():
    rich = RichMessage(elements=[TextElement(content="test")])
    msg = OutboundMessage(chat_id="c1", content=rich)
    assert isinstance(msg.content, RichMessage)
