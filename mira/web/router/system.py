"""系统信息与配额：/health /meta /quota。"""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict:
    return {"ok": True, "version": "0.2.0"}


@router.get("/meta")
def meta(request: Request) -> dict:
    client = request.app.state.client
    return {
        "agents": client.available_agents(),
        "providers": client.available_providers(),
    }


@router.get("/quota")
def quota(request: Request) -> dict:
    return request.app.state.client.quota_usage()
