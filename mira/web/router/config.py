"""配置中心（决策 #10）：/config。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from mira.web.router.models import UpdateConfigBody

router = APIRouter(prefix="/api")


@router.get("/config")
def get_config(request: Request) -> dict:
    return request.app.state.client.get_config()


@router.get("/config/models")
def config_models(
    request: Request, provider: str | None = None, type: str | None = None
) -> dict:
    """可用模型：provider=按已配置 id；type=按 litellm 前缀查 models.dev 目录。"""
    return request.app.state.client.get_models(provider, provider_type=type)


@router.put("/config")
def put_config(request: Request, body: UpdateConfigBody) -> dict:
    try:
        return request.app.state.client.update_config(body.section, body.data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
