import os
from dataclasses import dataclass, field

from nano_claude.setup import load_user_config


@dataclass
class ProviderConfig:
    name: str
    api_key: str | None = None
    base_url: str | None = None
    default_model: str = ""


PROVIDERS: dict[str, ProviderConfig] = {
    "openai": ProviderConfig(
        name="openai",
        default_model="gpt-4o",
    ),
    "deepseek": ProviderConfig(
        name="deepseek",
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-v4-flash",
    ),
    "anthropic": ProviderConfig(
        name="anthropic",
        base_url="https://api.anthropic.com/v1",
        default_model="claude-sonnet-4-20250514",
    ),
    "ollama": ProviderConfig(
        name="ollama",
        base_url="http://localhost:11434/v1",
        default_model="llama3",
    ),
}

MODEL_PROVIDER_PREFIX: dict[str, str] = {
    "gpt-": "openai",
    "o1-": "openai",
    "o3-": "openai",
    "o4-": "openai",
    "deepseek": "deepseek",
    "claude": "anthropic",
}


def detect_provider(model: str) -> str:
    model_lower = model.lower()
    for prefix, provider in MODEL_PROVIDER_PREFIX.items():
        if model_lower.startswith(prefix):
            return provider
    return os.environ.get("NANO_CLAUDE_PROVIDER", "openai")


def resolve_config(model: str | None = None) -> ProviderConfig:
    user_config = load_user_config() or {}

    resolved_model = (
        model
        or os.environ.get("NANO_CLAUDE_MODEL")
        or user_config.get("model")
        or "gpt-4o"
    )
    provider_name = detect_provider(resolved_model)

    provider = PROVIDERS.get(provider_name, PROVIDERS["openai"])
    config = ProviderConfig(
        name=provider.name,
        api_key=None,
        base_url=provider.base_url,
        default_model=resolved_model,
    )

    config.api_key = _resolve_api_key(provider_name, user_config)
    config.base_url = os.environ.get(f"{provider_name.upper()}_BASE_URL", provider.base_url)

    return config


def _resolve_api_key(provider_name: str, user_config: dict | None = None) -> str | None:
    user_config = user_config or {}
    env_var = f"{provider_name.upper()}_API_KEY"
    key = os.environ.get(env_var)
    if not key:
        key = os.environ.get("NANO_CLAUDE_API_KEY")
    if not key:
        key = user_config.get("api_key")
    if not key and provider_name == "ollama":
        key = "ollama"
    return key
