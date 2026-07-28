"""Provider management API routes — list, add, delete, refresh providers and models."""

import logging

from fastapi import APIRouter, HTTPException

from nano_claude.core.state import state
from nano_claude.infra.setup import save_user_config
from nano_claude.interfaces.web.services.provider_service import (
    ProviderInfo,
    fetch_models,
    get_default_base_url,
    get_provider_label,
    resolve_litellm_model,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/providers")
async def api_list_providers():
    """Return all configured providers and their cached models."""
    state.load_providers()
    result = []
    for p in state.providers.values():
        result.append({
            "name": p.name,
            "type": p.type,
            "label": get_provider_label(p.type),
            "base_url": p.base_url,
            "has_api_key": bool(p.api_key),
            "models": p.models,
        })
    return {"providers": result}


@router.post("/api/providers")
async def api_add_provider(body: dict):
    """Add a new provider. Fetches models from its API, creates config file."""
    name = (body.get("name") or "").strip()
    provider_type = (body.get("type") or "").strip()
    api_key = body.get("api_key") or None
    base_url = body.get("base_url") or get_default_base_url(provider_type)

    if not name:
        raise HTTPException(status_code=400, detail="Provider name is required")
    if not provider_type:
        raise HTTPException(status_code=400, detail="Provider type is required")

    if name in state.providers:
        raise HTTPException(status_code=400, detail=f"Provider '{name}' already exists")

    # Fetch models from the provider's API
    models = await fetch_models(provider_type, api_key, base_url)

    info = ProviderInfo(
        name=name,
        type=provider_type,
        api_key=api_key,
        base_url=base_url,
        models=models,
    )
    state.add_provider(info)

    return {
        "name": info.name,
        "type": info.type,
        "label": get_provider_label(info.type),
        "base_url": info.base_url,
        "has_api_key": bool(info.api_key),
        "models": info.models,
    }


@router.put("/api/providers/{name}")
async def api_update_provider(name: str, body: dict):
    """Update an existing provider. Re-fetches models if api_key/type/base_url changed."""
    if name not in state.providers:
        raise HTTPException(status_code=404, detail=f"Provider '{name}' not found")

    existing = state.providers[name]
    provider_type = body.get("type") or existing.type
    api_key = body.get("api_key") if "api_key" in body else existing.api_key
    base_url = body.get("base_url") if "base_url" in body else existing.base_url

    if not provider_type:
        raise HTTPException(status_code=400, detail="Provider type is required")

    # Re-fetch models if relevant fields changed
    type_changed = provider_type != existing.type
    key_changed = body.get("api_key") is not None and body["api_key"] != existing.api_key
    url_changed = "base_url" in body and body["base_url"] != existing.base_url
    should_refetch = type_changed or key_changed or url_changed

    models = existing.models
    if should_refetch:
        models = await fetch_models(provider_type, api_key, base_url)

    info = ProviderInfo(
        name=name,
        type=provider_type,
        api_key=api_key,
        base_url=base_url,
        models=models,
    )
    state.add_provider(info)

    return {
        "name": info.name,
        "type": info.type,
        "label": get_provider_label(info.type),
        "base_url": info.base_url,
        "has_api_key": bool(info.api_key),
        "models": info.models,
    }


@router.patch("/api/providers/{name}/models")
async def api_update_provider_models(name: str, body: dict):
    """Manually update the model list for a provider (e.g. for Copilot)."""
    if name not in state.providers:
        raise HTTPException(status_code=404, detail=f"Provider '{name}' not found")

    models = body.get("models")
    if not isinstance(models, list):
        raise HTTPException(status_code=400, detail="'models' must be a list of strings")

    existing = state.providers[name]
    info = ProviderInfo(
        name=name,
        type=existing.type,
        api_key=existing.api_key,
        base_url=existing.base_url,
        models=[m.strip() for m in models if isinstance(m, str) and m.strip()],
    )
    state.add_provider(info)

    return {
        "name": info.name,
        "type": info.type,
        "label": get_provider_label(info.type),
        "base_url": info.base_url,
        "has_api_key": bool(info.api_key),
        "models": info.models,
    }


@router.delete("/api/providers/{name}")
async def api_delete_provider(name: str):
    """Delete a provider config file and remove it from state."""
    if name not in state.providers:
        raise HTTPException(status_code=404, detail=f"Provider '{name}' not found")
    state.remove_provider(name)
    return {"ok": True}


@router.post("/api/providers/{name}/refresh")
async def api_refresh_provider(name: str):
    """Re-fetch models for a provider and update the config file."""
    if name not in state.providers:
        raise HTTPException(status_code=404, detail=f"Provider '{name}' not found")

    existing = state.providers[name]
    models = await fetch_models(existing.type, existing.api_key, existing.base_url)

    info = ProviderInfo(
        name=name,
        type=existing.type,
        api_key=existing.api_key,
        base_url=existing.base_url,
        models=models,
    )
    state.add_provider(info)

    return {
        "name": info.name,
        "type": info.type,
        "label": get_provider_label(info.type),
        "base_url": info.base_url,
        "has_api_key": bool(info.api_key),
        "models": info.models,
    }


@router.get("/api/models")
async def api_list_models():
    """Return all available models across all configured providers."""
    state.load_providers()
    result = []
    for p in state.providers.values():
        for model in p.models:
            litellm_model = resolve_litellm_model(p.type, model)
            result.append({
                "provider": p.name,
                "provider_type": p.type,
                "provider_label": get_provider_label(p.type),
                "model": model,
                "litellm_model": litellm_model,
                "display": f"{p.name}/{model}",
            })
    return {"models": result}


@router.post("/api/model")
async def api_set_model(body: dict):
    """Set the active model. Body: {model, provider} (raw names from dropdown)."""
    model = (body.get("model") or "").strip()
    provider_name = (body.get("provider") or "").strip()

    if not model:
        raise HTTPException(status_code=400, detail="Model name is required")
    if not provider_name:
        raise HTTPException(status_code=400, detail="Provider name is required")
    if provider_name not in state.providers:
        raise HTTPException(status_code=400, detail=f"Provider '{provider_name}' not found")
    if state.agent is None:
        raise HTTPException(status_code=400, detail="Agent not initialized. Please complete setup first.")

    provider = state.providers[provider_name]
    if model not in provider.models:
        raise HTTPException(status_code=400, detail=f"Model '{model}' not found in provider '{provider_name}'")

    litellm_model = resolve_litellm_model(provider.type, model)

    # Update the agent's LLM client
    state.agent.reconfigure_llm(
        model=litellm_model,
        api_key=provider.api_key,
        base_url=provider.base_url,
    )

    # Persist the selection to config.toml
    save_user_config(litellm_model, provider.api_key or "", provider=provider_name)

    # Track active provider on the agent
    state.agent.provider = provider_name

    return {
        "ok": True,
        "model": litellm_model,
        "provider": provider_name,
        "display": f"{provider_name}/{model}",
    }
