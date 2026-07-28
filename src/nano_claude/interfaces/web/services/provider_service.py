"""Provider management service — CRUD for provider config files and model fetching."""

import logging
import os
import tomllib
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".nano_claude")
PROVIDERS_DIR = os.path.join(CONFIG_DIR, "providers")


# ── Provider type defaults ──────────────────────────────────────────────

PROVIDER_DEFAULTS: dict[str, dict[str, str | None]] = {
    "openai": {"base_url": None},
    "deepseek": {"base_url": "https://api.deepseek.com/v1"},
    "anthropic": {"base_url": "https://api.anthropic.com/v1"},
    "ollama": {"base_url": "http://localhost:11434/v1"},
    "custom": {"base_url": None},
}

PROVIDER_LABELS: dict[str, str] = {
    "openai": "OpenAI",
    "deepseek": "DeepSeek",
    "anthropic": "Anthropic",
    "ollama": "Ollama",
    "custom": "Custom",
}


@dataclass
class ProviderInfo:
    name: str
    type: str
    api_key: str | None = None
    base_url: str | None = None
    models: list[str] = field(default_factory=list)


# ── Path helpers ────────────────────────────────────────────────────────

def get_providers_dir() -> str:
    os.makedirs(PROVIDERS_DIR, exist_ok=True)
    return PROVIDERS_DIR


def _provider_path(name: str) -> str:
    return os.path.join(PROVIDERS_DIR, f"{name}.toml")


# ── CRUD operations ─────────────────────────────────────────────────────

def list_providers() -> list[ProviderInfo]:
    """Read all provider .toml files from the providers directory."""
    get_providers_dir()
    if not os.path.isdir(PROVIDERS_DIR):
        return []
    results: list[ProviderInfo] = []
    for entry in sorted(os.listdir(PROVIDERS_DIR)):
        if not entry.endswith(".toml"):
            continue
        info = load_provider(entry[:-5])  # strip .toml
        if info is not None:
            results.append(info)
    return results


def load_provider(name: str) -> ProviderInfo | None:
    """Load a single provider by name. Returns None if not found or corrupt."""
    path = _provider_path(name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        provider = data.get("provider", {})
        if not isinstance(provider, dict):
            return None
        return ProviderInfo(
            name=name,
            type=provider.get("type", "custom"),
            api_key=provider.get("api_key"),
            base_url=provider.get("base_url"),
            models=provider.get("models", []),
        )
    except Exception as e:
        logger.warning("Failed to load provider %s: %s", name, e)
        return None


def save_provider(info: ProviderInfo) -> None:
    """Save/overwrite a provider config file."""
    get_providers_dir()
    path = _provider_path(info.name)

    lines = ["[provider]"]
    lines.append(f'type = "{info.type}"')
    if info.api_key:
        lines.append(f'api_key = "{info.api_key}"')
    if info.base_url:
        lines.append(f'base_url = "{info.base_url}"')
    if info.models:
        models_str = ", ".join(f'"{m}"' for m in info.models)
        lines.append(f"models = [{models_str}]")

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def delete_provider(name: str) -> bool:
    """Delete a provider config file. Returns True if deleted, False if not found."""
    path = _provider_path(name)
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


# ── Model fetching ──────────────────────────────────────────────────────

async def fetch_models(
    provider_type: str,
    api_key: str | None,
    base_url: str | None,
) -> list[str]:
    """Fetch available model IDs from the provider's API."""
    try:
        if provider_type == "anthropic":
            return await _fetch_anthropic_models(api_key)
        elif provider_type == "ollama":
            return await _fetch_ollama_models(base_url)
        else:
            # OpenAI-compatible (openai, deepseek, custom)
            return await _fetch_openai_compatible_models(base_url, api_key)
    except Exception as e:
        logger.warning("Failed to fetch models for %s: %s", provider_type, e)
        return []


async def _fetch_openai_compatible_models(
    base_url: str | None, api_key: str | None,
) -> list[str]:
    """GET {base_url}/models with Bearer auth."""
    url = _normalize_models_url(base_url, "openai")
    if not url:
        return []

    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return [m["id"] for m in data.get("data", []) if m.get("id")]


async def _fetch_anthropic_models(api_key: str | None) -> list[str]:
    """GET https://api.anthropic.com/v1/models with x-api-key auth."""
    url = "https://api.anthropic.com/v1/models"
    headers = {
        "Accept": "application/json",
        "anthropic-version": "2023-06-01",
    }
    if api_key:
        headers["x-api-key"] = api_key

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return [m["id"] for m in data.get("data", []) if m.get("id")]


async def _fetch_ollama_models(base_url: str | None) -> list[str]:
    """GET /api/tags from Ollama (not OpenAI-compatible /v1/models)."""
    url = _normalize_models_url(base_url, "ollama")
    if not url:
        url = "http://localhost:11434/api/tags"

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
        return [m["name"] for m in data.get("models", []) if m.get("name")]


# ── URL helpers ─────────────────────────────────────────────────────────

def _normalize_models_url(base_url: str | None, provider_type: str) -> str | None:
    """Build the correct model-list endpoint URL from a provider's base URL."""
    if not base_url:
        return None

    if provider_type == "ollama":
        base = base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        return f"{base}/api/tags"

    # OpenAI-compatible: {base_url}/models
    return f"{base_url.rstrip('/')}/models"


# ── litellm helpers ─────────────────────────────────────────────────────

def resolve_litellm_model(provider_type: str, model: str) -> str:
    """Convert a raw model name to a litellm-compatible model string.

    For Anthropic, prepend 'anthropic/' prefix (e.g. 'claude-sonnet-4' →
    'anthropic/claude-sonnet-4'). Other types are used as-is since litellm
    auto-detects them or they're handled via custom_llm_provider.
    """
    if provider_type == "anthropic":
        if not model.startswith("anthropic/"):
            return f"anthropic/{model}"
    return model


def get_default_base_url(provider_type: str) -> str | None:
    """Return the default base URL for a provider type."""
    defaults = PROVIDER_DEFAULTS.get(provider_type, {})
    return defaults.get("base_url")


def get_provider_label(provider_type: str) -> str:
    """Return a human-readable label for a provider type."""
    return PROVIDER_LABELS.get(provider_type, provider_type)
