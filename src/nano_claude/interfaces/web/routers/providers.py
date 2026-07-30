"""Provider management API routes — list, add, delete, refresh providers and models."""

import logging

from fastapi import APIRouter, HTTPException

from nano_claude.core.provider_service import (
    ProviderError,
    get_default_base_url,
    get_provider_label,
    resolve_litellm_model,
)
from nano_claude.core.state import state

logger = logging.getLogger(__name__)

router = APIRouter()


def _provider_to_dict(p):
    return {
        "name": p.name,
        "type": p.type,
        "label": get_provider_label(p.type),
        "base_url": p.base_url,
        "has_api_key": bool(p.api_key),
        "models": p.models,
    }


@router.get("/api/providers")
async def api_list_providers():
    """Return all configured providers and their cached models."""
    return {"providers": [_provider_to_dict(p) for p in state.get_providers().values()]}


@router.post("/api/providers")
async def api_add_provider(body: dict):
    """Add a new provider. Fetches models from its API, creates config file."""
    name = (body.get("name") or "").strip()
    provider_type = (body.get("type") or "").strip()
    api_key = body.get("api_key") or None
    base_url = body.get("base_url") or get_default_base_url(provider_type)

    try:
        info = await state.add_provider(name, provider_type, api_key, base_url)
    except ProviderError as e:
        status = 409 if "already exists" in str(e) else 400
        raise HTTPException(status_code=status, detail=str(e))

    return _provider_to_dict(info)


@router.put("/api/providers/{name}")
async def api_update_provider(name: str, body: dict):
    """Update an existing provider. Re-fetches models if api_key/type/base_url changed."""
    try:
        info = await state.update_provider(
            name,
            new_type=body.get("type"),
            api_key=body.get("api_key"),
            base_url=body.get("base_url"),
        )
    except ProviderError as e:
        status = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=status, detail=str(e))

    return _provider_to_dict(info)


@router.patch("/api/providers/{name}/models")
async def api_update_provider_models(name: str, body: dict):
    """Manually update the model list for a provider (e.g. for Copilot)."""
    models = body.get("models")
    if not isinstance(models, list):
        raise HTTPException(status_code=400, detail="'models' must be a list of strings")

    try:
        info = state.set_provider_models(name, models)
    except ProviderError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return _provider_to_dict(info)


@router.delete("/api/providers/{name}")
async def api_delete_provider(name: str):
    """Delete a provider config file and remove it from state."""
    try:
        state.remove_provider(name)
    except ProviderError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True}


@router.post("/api/providers/{name}/refresh")
async def api_refresh_provider(name: str):
    """Re-fetch models for a provider and update the config file."""
    try:
        info = await state.refresh_provider(name)
    except ProviderError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return _provider_to_dict(info)


@router.get("/api/models")
async def api_list_models():
    """Return all available models across all configured providers."""
    result = []
    for p in state.get_providers().values():
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
    if state.agent is None:
        raise HTTPException(status_code=400, detail="Agent not initialized. Please complete setup first.")

    try:
        provider = state.get_provider(provider_name)
    except ProviderError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if model not in provider.models:
        raise HTTPException(status_code=400, detail=f"Model '{model}' not found in provider '{provider_name}'")

    litellm_model = resolve_litellm_model(provider.type, model)

    state.agent.reconfigure_llm(
        model=litellm_model,
        api_key=provider.api_key,
        base_url=provider.base_url,
        provider=provider_name,
    )

    return {
        "ok": True,
        "model": litellm_model,
        "provider": provider_name,
        "display": f"{provider_name}/{model}",
    }
