from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from chatcc.main import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_auth_cli_channel(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["auth", "--channel", "cli"])
    assert result.exit_code == 0
    assert "无需认证" in result.output


def test_auth_unknown_channel(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["auth", "--channel", "unknown"])
    assert result.exit_code == 0
    assert "未知渠道" in result.output


def test_auth_telegram(runner: CliRunner, tmp_path) -> None:
    with patch("chatcc.main.CHATCC_HOME", tmp_path):
        result = runner.invoke(
            cli,
            ["auth", "--channel", "telegram"],
            input="123456:ABC-DEF\n\n",
        )
        assert result.exit_code == 0
        assert "认证完成" in result.output

        config_path = tmp_path / "config.yaml"
        assert config_path.exists()
        with open(config_path) as f:
            data = yaml.safe_load(f)
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

        config_path = tmp_path / "config.yaml"
        assert config_path.exists()
        with open(config_path) as f:
            data = yaml.safe_load(f)
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
        assert "格式无效" in result.output

        config_path = tmp_path / "config.yaml"
        assert not config_path.exists()
