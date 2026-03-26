import pytest
from pathlib import Path
from chatcc.config import (
    AppConfig,
    ChannelConfig,
    AgentConfig,
    ProviderConfig,
    SecurityConfig,
    load_config,
)


def test_default_config():
    config = AppConfig()
    assert config.channel.type == "cli"
    assert config.agent.active_provider == "anthropic"
    assert config.data_dir is not None
    assert config.workspace is not None


def test_load_config_from_yaml(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
channel:
  type: telegram
  telegram:
    token: "test-token"
    allowed_users:
      - "123"

agent:
  active_provider: anthropic
  providers:
    anthropic:
      name: Anthropic
      model: claude-haiku-4-20250414
      api_key: "sk-test"
""")
    config = load_config(config_file)
    assert config.channel.type == "telegram"
    assert config.channel.telegram["token"] == "test-token"
    assert config.agent.providers["anthropic"].model == "claude-haiku-4-20250414"


def test_env_var_expansion(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_TOKEN", "my-secret-token")
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
channel:
  type: telegram
  telegram:
    token: "${TEST_TOKEN}"
    allowed_users: []
""")
    config = load_config(config_file)
    assert config.channel.telegram["token"] == "my-secret-token"
