"""Tests for channel interactive_setup methods."""

from __future__ import annotations

import pytest

from tests.test_setup_ui import FakeSetupUI


def test_telegram_interactive_setup():
    from chatcc.channel.telegram import TelegramChannel

    ui = FakeSetupUI(["123456:ABCDEF", "user1, user2"])
    result = TelegramChannel.interactive_setup(ui)

    assert result["token"] == "123456:ABCDEF"
    assert result["allowed_users"] == ["user1", "user2"]


def test_telegram_interactive_setup_no_allowed_users():
    from chatcc.channel.telegram import TelegramChannel

    ui = FakeSetupUI(["123456:ABCDEF", ""])
    result = TelegramChannel.interactive_setup(ui)

    assert result["token"] == "123456:ABCDEF"
    assert result["allowed_users"] == []


def test_telegram_interactive_setup_invalid_token():
    from chatcc.channel.telegram import TelegramChannel

    ui = FakeSetupUI(["invalid-no-colon", ""])
    with pytest.raises(ValueError, match="格式无效"):
        TelegramChannel.interactive_setup(ui)


def test_feishu_interactive_setup():
    from chatcc.channel.feishu import FeishuChannel

    ui = FakeSetupUI(["app-id-123", "secret-456", "ou_abc, ou_def"])
    result = FeishuChannel.interactive_setup(ui)

    assert result["app_id"] == "app-id-123"
    assert result["app_secret"] == "secret-456"
    assert result["allowed_users"] == ["ou_abc", "ou_def"]


def test_feishu_interactive_setup_empty_creds():
    from chatcc.channel.feishu import FeishuChannel

    ui = FakeSetupUI(["", "", ""])
    with pytest.raises(ValueError, match="不能为空"):
        FeishuChannel.interactive_setup(ui)


def test_base_channel_interactive_setup_returns_empty():
    from chatcc.channel.base import MessageChannel

    ui = FakeSetupUI([])
    result = MessageChannel.interactive_setup(ui)
    assert result == {}
