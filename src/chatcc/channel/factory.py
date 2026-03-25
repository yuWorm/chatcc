from __future__ import annotations

from typing import Any

from chatcc.channel.base import MessageChannel
from chatcc.config import ChannelConfig


CHANNEL_REGISTRY: dict[str, tuple[str, str]] = {
    "cli": ("chatcc.channel.cli", "CliChannel"),
    "telegram": ("chatcc.channel.telegram", "TelegramChannel"),
    "feishu": ("chatcc.channel.feishu", "FeishuChannel"),
    "wechat": ("chatcc.channel.wechatbot", "WeChatChannel"),
}

CHANNEL_LABELS: list[tuple[str, str]] = [
    ("telegram", "Telegram"),
    ("feishu", "飞书 (Feishu)"),
    ("wechat", "微信 (WeChat)"),
    ("cli", "CLI (终端调试)"),
]


def get_channel_class(channel_type: str) -> type[MessageChannel]:
    """获取渠道类 (不实例化)，用于调用 interactive_setup 等静态方法。"""
    import importlib

    entry = CHANNEL_REGISTRY.get(channel_type)
    if not entry:
        raise ValueError(f"Unknown channel type: {channel_type}")

    module_path, class_name = entry
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def create_channel(config: ChannelConfig) -> MessageChannel:
    cls = get_channel_class(config.type)
    channel_config: dict[str, Any] = getattr(config, config.type, {})
    if config.type == "cli":
        return cls()
    return cls(channel_config)
