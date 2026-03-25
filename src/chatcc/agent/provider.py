from __future__ import annotations

from typing import Literal

from pydantic_ai.models import Model, infer_model
from pydantic_ai.providers import infer_provider, Provider

from chatcc.config import ProviderConfig

OFFICIAL_PREFIXES: dict[str, str] = {
    "anthropic": "anthropic",
    "openai": "openai",
    "openai-responses": "openai-responses",
    "google": "google-gla",
}


def _build_provider(
    prefix: str,
    api_key: str | None,
    base_url: str | None = None,
) -> Provider:
    """构建 provider，优先使用配置中的 api_key / base_url，否则 fallback 到环境变量。"""
    match prefix:
        case "anthropic":
            if api_key or base_url:
                from pydantic_ai.providers.anthropic import AnthropicProvider
                kwargs: dict[str, str] = {}
                if api_key:
                    kwargs["api_key"] = api_key
                if base_url:
                    kwargs["base_url"] = base_url
                return AnthropicProvider(**kwargs)

        case "openai" | "openai-responses":
            if api_key or base_url:
                from pydantic_ai.providers.openai import OpenAIProvider
                kwargs = {}
                if api_key:
                    kwargs["api_key"] = api_key
                if base_url:
                    kwargs["base_url"] = base_url
                return OpenAIProvider(**kwargs)

        case "google-gla":
            if api_key or base_url:
                from pydantic_ai.providers.google import GoogleProvider
                kwargs = {}
                if api_key:
                    kwargs["api_key"] = api_key
                if base_url:
                    kwargs["base_url"] = base_url
                return GoogleProvider(**kwargs)

    return infer_provider(prefix)


def _build_openai_model(
    model_name: str,
    api_key: str | None,
    base_url: str | None,
    model_type: Literal["chat", "responses"],
) -> Model:
    """为自定义 OpenAI 兼容供应商构建 Chat 或 Responses 模型。"""
    from pydantic_ai.providers.openai import OpenAIProvider

    kwargs: dict[str, str] = {}
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    provider = OpenAIProvider(**kwargs)

    if model_type == "responses":
        from pydantic_ai.models.openai import OpenAIResponsesModel
        return OpenAIResponsesModel(model_name, provider=provider)

    from pydantic_ai.models.openai import OpenAIChatModel
    return OpenAIChatModel(model_name, provider=provider)


def build_model_from_config(
    providers: dict[str, ProviderConfig],
    active: str,
) -> Model:
    provider_cfg = providers[active]

    if active not in OFFICIAL_PREFIXES:
        return _build_openai_model(
            provider_cfg.model,
            provider_cfg.api_key or None,
            provider_cfg.base_url,
            model_type="responses" if provider_cfg.type == "responses" else "chat",
        )

    prefix = OFFICIAL_PREFIXES[active]
    prov = _build_provider(prefix, provider_cfg.api_key or None, provider_cfg.base_url)
    model_id = f"{prefix}:{provider_cfg.model}"
    return infer_model(model_id, provider_factory=lambda _name: prov)
