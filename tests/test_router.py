import pytest
from chatcc.router.router import MessageRouter
from chatcc.channel.message import InboundMessage


@pytest.fixture
def router():
    return MessageRouter()


async def test_intercept_y_command(router):
    msg = InboundMessage(sender_id="u1", content="/y 3", chat_id="c1")
    result = await router.route(msg)
    assert result.intercepted is True
    assert result.command == "/y"
    assert result.args == ["3"]


async def test_intercept_n_command(router):
    msg = InboundMessage(sender_id="u1", content="/n", chat_id="c1")
    result = await router.route(msg)
    assert result.intercepted is True
    assert result.command == "/n"


async def test_intercept_pending(router):
    msg = InboundMessage(sender_id="u1", content="/pending", chat_id="c1")
    result = await router.route(msg)
    assert result.intercepted is True


async def test_intercept_stop(router):
    msg = InboundMessage(sender_id="u1", content="/stop", chat_id="c1")
    result = await router.route(msg)
    assert result.intercepted is True


async def test_intercept_status(router):
    msg = InboundMessage(sender_id="u1", content="/status", chat_id="c1")
    result = await router.route(msg)
    assert result.intercepted is True


async def test_normal_message_not_intercepted(router):
    msg = InboundMessage(sender_id="u1", content="帮我实现登录功能", chat_id="c1")
    result = await router.route(msg)
    assert result.intercepted is False
    assert result.message == msg


async def test_y_all_command(router):
    msg = InboundMessage(sender_id="u1", content="/y all", chat_id="c1")
    result = await router.route(msg)
    assert result.intercepted is True
    assert result.command == "/y"
    assert result.args == ["all"]
