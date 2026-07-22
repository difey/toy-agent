import os
import tomllib
from dataclasses import dataclass, field
from importlib.resources import files

from nano_claude.infra.setup import load_user_config


@dataclass
class ProviderConfig:
    name: str
    api_key: str | None = None
    base_url: str | None = None
    default_model: str = ""


def _load_default_providers() -> dict[str, ProviderConfig]:
    """Load built-in provider defaults from the packaged default_config.toml."""
    data = tomllib.loads(
        files("nano_claude.infra").joinpath("config", "default_config.toml").read_text()
    )
    providers = {}
    for name, values in data.get("providers", {}).items():
        providers[name] = ProviderConfig(
            name=name,
            base_url=values.get("base_url"),
            default_model=values.get("default_model", ""),
        )
    return providers


PROVIDERS: dict[str, ProviderConfig] = _load_default_providers()

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
