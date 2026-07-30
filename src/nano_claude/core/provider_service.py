"""Provider management — in-memory cache, CRUD, model fetching, validation."""

import logging
import os
import tomllib
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".nano_claude")
PROVIDERS_DIR = os.path.join(CONFIG_DIR, "providers")


# ── Exceptions ────────────────────────────────────────────────────────────

class ProviderError(Exception):
    """Base provider error."""

class ProviderNotFoundError(ProviderError):
    """Provider does not exist."""

class ProviderAlreadyExistsError(ProviderError):
    """Provider already exists."""

class ProviderValidationError(ProviderError):
    """Invalid provider parameters."""


# ── Data types ────────────────────────────────────────────────────────────

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


# ── File I/O helpers ──────────────────────────────────────────────────────

def _get_providers_dir() -> str:
    os.makedirs(PROVIDERS_DIR, exist_ok=True)
    return PROVIDERS_DIR


def _provider_path(name: str) -> str:
    return os.path.join(PROVIDERS_DIR, f"{name}.toml")


def _load_provider_from_disk(name: str) -> ProviderInfo | None:
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


def _save_provider_to_disk(info: ProviderInfo) -> None:
    _get_providers_dir()
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


def _delete_provider_from_disk(name: str) -> bool:
    path = _provider_path(name)
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


# ── Model fetching ────────────────────────────────────────────────────────

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
            return await _fetch_openai_compatible_models(base_url, api_key)
    except Exception as e:
        logger.warning("Failed to fetch models for %s: %s", provider_type, e)
        return []


async def _fetch_openai_compatible_models(
    base_url: str | None, api_key: str | None,
) -> list[str]:
    url = _normalize_models_url(base_url, "openai")
    if not url:
        return []
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"******"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return [m["id"] for m in data.get("data", []) if m.get("id")]


async def _fetch_anthropic_models(api_key: str | None) -> list[str]:
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
    url = _normalize_models_url(base_url, "ollama")
    if not url:
        url = "http://localhost:11434/api/tags"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
        return [m["name"] for m in data.get("models", []) if m.get("name")]


def _normalize_models_url(base_url: str | None, provider_type: str) -> str | None:
    if not base_url:
        return None
    if provider_type == "ollama":
        base = base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        return f"{base}/api/tags"
    return f"{base_url.rstrip('/')}/models"


# ── litellm helpers ───────────────────────────────────────────────────────

def resolve_litellm_model(provider_type: str, model: str) -> str:
    """Convert a raw model name to a litellm-compatible model string."""
    if provider_type == "anthropic":
        if not model.startswith("anthropic/"):
            return f"anthropic/{model}"
    return model


def get_default_base_url(provider_type: str) -> str | None:
    defaults = PROVIDER_DEFAULTS.get(provider_type, {})
    return defaults.get("base_url")


def get_provider_label(provider_type: str) -> str:
    return PROVIDER_LABELS.get(provider_type, provider_type)


# ── ProviderManager ───────────────────────────────────────────────────────

class ProviderManager:
    """In-memory provider cache with disk-backed persistence."""

    def __init__(self):
        self._cache: dict[str, ProviderInfo] = {}

    # ── Internal ──────────────────────────────────────────────────────

    def _reload_from_disk(self) -> None:
        _get_providers_dir()
        if not os.path.isdir(PROVIDERS_DIR):
            self._cache = {}
            return
        self._cache = {}
        for entry in sorted(os.listdir(PROVIDERS_DIR)):
            if not entry.endswith(".toml"):
                continue
            info = _load_provider_from_disk(entry[:-5])
            if info is not None:
                self._cache[info.name] = info

    def _sync_to_cache(self, name: str) -> None:
        info = _load_provider_from_disk(name)
        if info is not None:
            self._cache[name] = info

    def _assert_exists(self, name: str) -> ProviderInfo:
        info = self._cache.get(name)
        if info is None:
            raise ProviderNotFoundError(f"Provider '{name}' not found")
        return info

    # ── Query ─────────────────────────────────────────────────────────

    def get_all(self) -> dict[str, ProviderInfo]:
        """Reload from disk and return all cached providers."""
        self._reload_from_disk()
        return dict(self._cache)

    def get(self, name: str) -> ProviderInfo:
        self._reload_from_disk()
        return self._assert_exists(name)

    def exists(self, name: str) -> bool:
        self._reload_from_disk()
        return name in self._cache

    # ── Mutations ─────────────────────────────────────────────────────

    async def add(
        self,
        name: str,
        provider_type: str,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        skip_fetch_models: bool = False,
    ) -> ProviderInfo:
        """Add a new provider: validate, fetch models, persist to disk, update cache.

        Raises:
            ProviderValidationError:  name/type is empty.
            ProviderAlreadyExistsError:  provider already exists.
            ProviderError:  other failures.
        """
        name = (name or "").strip()
        provider_type = (provider_type or "").strip()
        base_url = base_url or get_default_base_url(provider_type)

        if not name:
            raise ProviderValidationError("Provider name is required")
        if not provider_type:
            raise ProviderValidationError("Provider type is required")

        self._reload_from_disk()
        if name in self._cache:
            raise ProviderAlreadyExistsError(f"Provider '{name}' already exists")

        models: list[str] = []
        if not skip_fetch_models:
            models = await fetch_models(provider_type, api_key, base_url)

        info = ProviderInfo(
            name=name,
            type=provider_type,
            api_key=api_key,
            base_url=base_url,
            models=models,
        )
        _save_provider_to_disk(info)
        self._cache[info.name] = info
        return info

    async def update(
        self,
        name: str,
        *,
        new_type: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        skip_fetch_models: bool = False,
    ) -> ProviderInfo:
        """Update an existing provider. Re-fetches models if type/api_key/base_url changed."""
        existing = self._assert_exists(name)

        provider_type = new_type or existing.type
        merged_api_key = api_key if api_key is not None else existing.api_key
        merged_base_url = base_url if base_url is not None else existing.base_url

        if not provider_type:
            raise ProviderValidationError("Provider type is required")

        type_changed = new_type is not None and new_type != existing.type
        key_changed = api_key is not None and api_key != existing.api_key
        url_changed = base_url is not None and base_url != existing.base_url
        should_refetch = (type_changed or key_changed or url_changed) and not skip_fetch_models

        models = existing.models
        if should_refetch:
            models = await fetch_models(provider_type, merged_api_key, merged_base_url)

        info = ProviderInfo(
            name=name,
            type=provider_type,
            api_key=merged_api_key,
            base_url=merged_base_url,
            models=models,
        )
        _save_provider_to_disk(info)
        self._cache[name] = info
        return info

    async def refresh(self, name: str) -> ProviderInfo:
        """Re-fetch models for an existing provider."""
        existing = self._assert_exists(name)
        models = await fetch_models(existing.type, existing.api_key, existing.base_url)
        info = ProviderInfo(
            name=name,
            type=existing.type,
            api_key=existing.api_key,
            base_url=existing.base_url,
            models=models,
        )
        _save_provider_to_disk(info)
        self._cache[name] = info
        return info

    def set_models(self, name: str, models: list[str]) -> ProviderInfo:
        """Manually set models for a provider (e.g. for Copilot)."""
        existing = self._assert_exists(name)
        info = ProviderInfo(
            name=name,
            type=existing.type,
            api_key=existing.api_key,
            base_url=existing.base_url,
            models=[m.strip() for m in models if isinstance(m, str) and m.strip()],
        )
        _save_provider_to_disk(info)
        self._cache[name] = info
        return info

    def remove(self, name: str) -> None:
        """Delete a provider from disk and cache."""
        self._assert_exists(name)
        _delete_provider_from_disk(name)
        self._cache.pop(name, None)
