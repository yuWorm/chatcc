import pytest
from chatcc.channel.factory import create_channel
from chatcc.channel.cli import CliChannel
from chatcc.config import ChannelConfig


def test_create_cli_channel():
    config = ChannelConfig(type="cli")
    channel = create_channel(config)
    assert isinstance(channel, CliChannel)


def test_create_unknown_channel():
    config = ChannelConfig(type="unknown")
    with pytest.raises(ValueError, match="unknown"):
        create_channel(config)
