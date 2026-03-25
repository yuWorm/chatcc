import pytest
from chatcc.channel.base import MessageChannel
from chatcc.channel.message import OutboundMessage, RichMessage


def test_cannot_instantiate_abstract():
    with pytest.raises(TypeError):
        MessageChannel()


def test_concrete_implementation():
    class DummyChannel(MessageChannel):
        async def start(self) -> None: pass
        async def stop(self) -> None: pass
        async def send(self, message: OutboundMessage) -> None: pass
        def render(self, message: RichMessage): return str(message)
        def on_message(self, callback) -> None: pass
        def is_authenticated(self) -> bool: return True

    channel = DummyChannel()
    assert channel.is_authenticated()
