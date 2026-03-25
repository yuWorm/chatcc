"""Tests for channel factory — get_channel_class and create_channel."""

from __future__ import annotations

import pytest

from chatcc.channel.factory import (
    CHANNEL_LABELS,
    CHANNEL_REGISTRY,
    get_channel_class,
)


def test_registry_covers_labels():
    label_keys = {k for k, _ in CHANNEL_LABELS}
    assert label_keys.issubset(CHANNEL_REGISTRY.keys())


def test_get_channel_class_cli():
    from chatcc.channel.cli import CliChannel

    assert get_channel_class("cli") is CliChannel


def test_get_channel_class_telegram():
    from chatcc.channel.telegram import TelegramChannel

    assert get_channel_class("telegram") is TelegramChannel


def test_get_channel_class_feishu():
    from chatcc.channel.feishu import FeishuChannel

    assert get_channel_class("feishu") is FeishuChannel


def test_get_channel_class_unknown():
    with pytest.raises(ValueError, match="Unknown channel type"):
        get_channel_class("whatsapp")
