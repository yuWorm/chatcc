"""Tests for chatcc auth and chatcc init CLI commands."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from chatcc.main import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# auth command
# ---------------------------------------------------------------------------

def test_auth_cli_channel(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["auth", "--channel", "cli"])
    assert result.exit_code == 0
    assert "无需认证" in result.output


def test_auth_unknown_channel(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["auth", "--channel", "unknown"])
    assert result.exit_code != 0 or "Unknown channel type" in str(result.exception)


def test_auth_telegram(runner: CliRunner, tmp_path) -> None:
    with patch("chatcc.main.CHATCC_HOME", tmp_path):
        result = runner.invoke(
            cli,
            ["auth", "--channel", "telegram"],
            input="123456:ABC-DEF\n\n",
        )
        assert result.exit_code == 0
        assert "认证完成" in result.output

        data = yaml.safe_load((tmp_path / "config.yaml").read_text())
        assert data["channel"]["type"] == "telegram"
        assert data["channel"]["telegram"]["token"] == "123456:ABC-DEF"


def test_auth_feishu(runner: CliRunner, tmp_path) -> None:
    with patch("chatcc.main.CHATCC_HOME", tmp_path):
        result = runner.invoke(
            cli,
            ["auth", "--channel", "feishu"],
            input="cli_app_id\ncli_secret\n\n",
        )
        assert result.exit_code == 0
        assert "认证完成" in result.output

        data = yaml.safe_load((tmp_path / "config.yaml").read_text())
        assert data["channel"]["type"] == "feishu"
        assert data["channel"]["feishu"]["app_id"] == "cli_app_id"
        assert data["channel"]["feishu"]["app_secret"] == "cli_secret"


def test_auth_telegram_invalid_token(runner: CliRunner, tmp_path) -> None:
    with patch("chatcc.main.CHATCC_HOME", tmp_path):
        result = runner.invoke(
            cli,
            ["auth", "--channel", "telegram"],
            input="invalid-no-colon\n\n",
        )
        assert result.exit_code == 0
        assert "格式无效" in result.output or "无效" in result.output
        assert not (tmp_path / "config.yaml").exists()


def test_auth_choose_channel_interactively(runner: CliRunner, tmp_path) -> None:
    """When no --channel and config type is cli, prompt user to choose."""
    with patch("chatcc.main.CHATCC_HOME", tmp_path):
        result = runner.invoke(
            cli,
            ["auth"],
            input="1\n123456:ABC-DEF\nuser1\n",
        )
        assert result.exit_code == 0
        assert "认证完成" in result.output


# ---------------------------------------------------------------------------
# init command
# ---------------------------------------------------------------------------

def test_init_full_flow(runner: CliRunner, tmp_path) -> None:
    with patch("chatcc.main.CHATCC_HOME", tmp_path):
        result = runner.invoke(
            cli,
            ["init"],
            input="\n".join([
                "1",                    # choose provider: Anthropic
                "claude-sonnet-4-20250514",  # model
                "sk-test-key",          # api key
                "1",                    # choose channel: Telegram
                "123456:ABCDEF",        # token
                "user1",               # allowed users
            ]),
        )

        assert result.exit_code == 0, result.output
        assert "初始化完成" in result.output

        data = yaml.safe_load((tmp_path / "config.yaml").read_text())
        assert data["agent"]["active_provider"] == "anthropic"
        assert data["agent"]["providers"]["anthropic"]["api_key"] == "sk-test-key"
        assert data["channel"]["type"] == "telegram"
        assert data["channel"]["telegram"]["token"] == "123456:ABCDEF"


def test_init_custom_provider(runner: CliRunner, tmp_path) -> None:
    with patch("chatcc.main.CHATCC_HOME", tmp_path):
        result = runner.invoke(
            cli,
            ["init"],
            input="\n".join([
                "3",                    # choose provider: custom
                "my-llm",              # provider name
                "https://api.example.com/v1",  # base_url
                "my-model",            # model
                "api-key-123",         # api key
                "3",                    # choose channel: CLI
            ]),
        )

        assert result.exit_code == 0, result.output
        assert "初始化完成" in result.output

        data = yaml.safe_load((tmp_path / "config.yaml").read_text())
        assert data["agent"]["active_provider"] == "my-llm"
        assert data["agent"]["providers"]["my-llm"]["base_url"] == "https://api.example.com/v1"
