import pytest
from chatcc.agent.provider import build_model_from_config
from chatcc.config import ProviderConfig


def test_build_official_anthropic():
    from pydantic_ai.models.anthropic import AnthropicModel

    providers = {
        "anthropic": ProviderConfig(
            name="Anthropic",
            model="claude-haiku-4-20250414",
            api_key="sk-test",
        )
    }
    model = build_model_from_config(providers, "anthropic")
    assert isinstance(model, AnthropicModel)


def test_build_official_openai():
    from pydantic_ai.models.openai import OpenAIChatModel

    providers = {
        "openai": ProviderConfig(
            name="OpenAI",
            model="gpt-4o-mini",
            api_key="sk-test",
        )
    }
    model = build_model_from_config(providers, "openai")
    assert isinstance(model, OpenAIChatModel)


def test_build_openai_responses():
    from pydantic_ai.models.openai import OpenAIResponsesModel

    providers = {
        "openai-responses": ProviderConfig(
            name="OpenAI Responses",
            model="gpt-4o",
            api_key="sk-test",
        )
    }
    model = build_model_from_config(providers, "openai-responses")
    assert isinstance(model, OpenAIResponsesModel)


def test_build_google():
    from pydantic_ai.models.google import GoogleModel

    providers = {
        "google": ProviderConfig(
            name="Google",
            model="gemini-2.5-pro",
            api_key="test-key",
        )
    }
    model = build_model_from_config(providers, "google")
    assert isinstance(model, GoogleModel)


def test_build_custom_provider():
    from pydantic_ai.models.openai import OpenAIChatModel

    providers = {
        "custom": ProviderConfig(
            name="Custom",
            model="my-model",
            api_key="sk-test",
            base_url="https://api.custom.com/v1",
        )
    }
    model = build_model_from_config(providers, "custom")
    assert isinstance(model, OpenAIChatModel)


def test_unknown_provider():
    with pytest.raises(KeyError):
        build_model_from_config({}, "nonexistent")
