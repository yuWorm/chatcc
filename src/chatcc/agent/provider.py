from __future__ import annotations

from pydantic_ai.models import Model, infer_model
from pydantic_ai.providers import infer_provider, Provider

from chatcc.config import ProviderConfig


OFFICIAL_PREFIXES = {
    "anthropic": "anthropic",
    "openai": "openai",
    "openai-responses": "openai-responses",
    "google": "google-gla",
}


def _build_provider(prefix: str, api_key: str | None) -> Provider:
    """构建 provider，优先使用配置中的 api_key，否则 fallback 到环境变量。"""
    if api_key:
        match prefix:
            case "anthropic":
                from pydantic_ai.providers.anthropic import AnthropicProvider
                return AnthropicProvider(api_key=api_key)
            case "openai" | "openai-responses":
                from pydantic_ai.providers.openai import OpenAIProvider
                return OpenAIProvider(api_key=api_key)
            case "google-gla":
                from pydantic_ai.providers.google import GoogleProvider
                return GoogleProvider(api_key=api_key)

    return infer_provider(prefix)


def build_model_from_config(
    providers: dict[str, ProviderConfig],
    active: str,
) -> Model:
    provider_cfg = providers[active]

    if provider_cfg.base_url:
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        return OpenAIChatModel(
            provider_cfg.model,
            provider=OpenAIProvider(
                base_url=provider_cfg.base_url,
                api_key=provider_cfg.api_key,
            ),
        )

    prefix = OFFICIAL_PREFIXES.get(active, active)
    model_id = f"{prefix}:{provider_cfg.model}"
    prov = _build_provider(prefix, provider_cfg.api_key)
    return infer_model(model_id, provider_factory=lambda _name: prov)
