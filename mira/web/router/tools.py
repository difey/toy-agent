"""内建工具目录：/api/tools 返回当前注册的全部内建工具名（配置中心工具候选来源）。

新增内建工具只需注册进 ToolRegistry.with_builtins()，前端候选自动跟随，无需再改前端硬编码列表。
"""

from __future__ import annotations

from fastapi import APIRouter

from mira.core.tools.registry import ToolRegistry

router = APIRouter(prefix="/api")


@router.get("/tools")
def list_tools() -> dict:
    names = set(ToolRegistry.with_builtins().names())
    # dispatch_task 由 session runtime 对 dispatch=auto 的 agent 动态注册（不属于 with_builtins），
    # 但它是 agent 的可配置工具，须纳入配置中心候选，避免前端写死。
    names.add("dispatch_task")
    return {"tools": sorted(names)}
