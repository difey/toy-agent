"""内建工具：todowrite — 会话内持久化的多步任务清单。

存储于当前会话目录 sessions/<session_id>/todos.json（MIRA_HOME 可重定向，测试隔离）。
参考 nano_claude.tools.todowrite。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from mira import paths
from mira.core.tools.base import Tool, ToolContext, ToolResult, truncate_output

_STATUSES = {"pending", "in_progress", "completed", "cancelled"}
_PRIORITIES = {"high", "medium", "low"}


def _save_todos(store: Path, todos: list[dict]) -> None:
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(
        json.dumps(todos, ensure_ascii=False, indent=2), encoding="utf-8"
    )


class TodoWriteTool(Tool):
    name = "todowrite"
    description = (
        "创建并管理结构化任务清单（多步任务进度跟踪）。每项含 content/status（pending/"
        "in_progress/completed/cancelled）与 priority（high/medium/low）。"
        "提供完整列表即整表替换；持久化到当前会话目录。"
    )
    params_schema = {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "description": "完整 todo 列表（覆盖整个清单）",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "任务描述"},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed", "cancelled"],
                            "description": "任务状态",
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                            "description": "优先级",
                        },
                    },
                    "required": ["content", "status", "priority"],
                },
            }
        },
        "required": ["todos"],
    }

    def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
        todos = args.get("todos")
        if not isinstance(todos, list):
            return ToolResult(ok=False, error="todos 需为数组（提供完整清单）")

        normalized: list[dict] = []
        for t in todos:
            if not isinstance(t, dict):
                return ToolResult(ok=False, error="todos 元素需为对象")
            status = str(t.get("status", "pending"))
            priority = str(t.get("priority", "medium"))
            if status not in _STATUSES:
                return ToolResult(ok=False, error=f"非法状态: {status}")
            if priority not in _PRIORITIES:
                return ToolResult(ok=False, error=f"非法优先级: {priority}")
            normalized.append(
                {"content": str(t.get("content", "")), "status": status, "priority": priority}
            )

        t0 = time.perf_counter()
        # 写到当前 session 自己的目录（任务清单随会话隔离）
        store = paths.session_dir(ctx.workspace, ctx.session_id) / "todos.json"
        _save_todos(store, normalized)

        active = [t for t in normalized if t["status"] not in ("completed", "cancelled")]
        completed = sum(1 for t in normalized if t["status"] == "completed")
        cancelled = sum(1 for t in normalized if t["status"] == "cancelled")
        parts = []
        if active:
            parts.append(f"{len(active)} active")
        if completed:
            parts.append(f"{completed} completed")
        if cancelled:
            parts.append(f"{cancelled} cancelled")
        summary = ", ".join(parts) if parts else "0 todos"

        truncated, out = truncate_output(
            f"{summary}\n" + json.dumps(normalized, ensure_ascii=False, indent=2)
        )
        return ToolResult(
            ok=True,
            output=out,
            truncated=truncated,
            duration_ms=round((time.perf_counter() - t0) * 1000, 1),
        )
