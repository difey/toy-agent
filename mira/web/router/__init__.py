"""REST 路由包：按职责拆分的各子路由在此聚合。

server.py 通过 ``from mira.web.router import router`` 挂载全部 REST 接口。
"""

from __future__ import annotations

from fastapi import APIRouter

from mira.web.router import approvals, config, events, fs, sessions, system, tools, workspaces

router = APIRouter()
for _mod in (system, config, workspaces, sessions, approvals, events, fs, tools):
    router.include_router(_mod.router)

__all__ = ["router"]
