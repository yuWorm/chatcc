from __future__ import annotations

from chatcc.config import ProviderConfig


OFFICIAL_PREFIXES = {
    "anthropic": "anthropic",
    "openai": "openai",
    "google": "google-gla",
}


def build_model_from_config(
    providers: dict[str, ProviderConfig],
    active: str,
):
    provider = providers[active]

    if provider.base_url:
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        return OpenAIChatModel(
            provider.model,
            provider=OpenAIProvider(
                base_url=provider.base_url,
                api_key=provider.api_key,
            ),
        )

    prefix = OFFICIAL_PREFIXES.get(active, active)
    return f"{prefix}:{provider.model}"
