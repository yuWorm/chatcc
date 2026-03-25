import pytest
from chatcc.agent.provider import build_model_from_config
from chatcc.config import ProviderConfig


def test_build_official_anthropic():
    providers = {
        "anthropic": ProviderConfig(
            name="Anthropic",
            model="claude-haiku-4-20250414",
            api_key="sk-test",
        )
    }
    model = build_model_from_config(providers, "anthropic")
    assert model == "anthropic:claude-haiku-4-20250414"


def test_build_official_openai():
    providers = {
        "openai": ProviderConfig(
            name="OpenAI",
            model="gpt-4o-mini",
            api_key="sk-test",
        )
    }
    model = build_model_from_config(providers, "openai")
    assert model == "openai:gpt-4o-mini"


def test_build_custom_provider():
    providers = {
        "custom": ProviderConfig(
            name="Custom",
            model="my-model",
            api_key="sk-test",
            base_url="https://api.custom.com/v1",
        )
    }
    model = build_model_from_config(providers, "custom")
    assert hasattr(model, "model_name")


def test_unknown_provider():
    with pytest.raises(KeyError):
        build_model_from_config({}, "nonexistent")
