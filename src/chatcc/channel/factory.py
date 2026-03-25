from __future__ import annotations

from chatcc.channel.base import MessageChannel
from chatcc.config import ChannelConfig


def create_channel(config: ChannelConfig) -> MessageChannel:
    match config.type:
        case "cli":
            from chatcc.channel.cli import CliChannel
            return CliChannel()
        case "telegram":
            from chatcc.channel.telegram import TelegramChannel
            return TelegramChannel(config.telegram)
        case "feishu":
            from chatcc.channel.feishu import FeishuChannel
            return FeishuChannel(config.feishu)
        case _:
            raise ValueError(f"Unknown channel type: {config.type}")
