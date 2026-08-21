"""内建工具：project_memory — 工作区级项目记忆（agent 自动维护）。

存储于 workspace 数据目录的**唯一**记忆文件（MIRA_HOME 可重定向，测试隔离）：
    ~/.mira-code/workspaces/<ws_id>/memory.md

操作（operation）：
- read    读取当前记忆全文（文件不存在返回空态提示）
- append  在文件末尾追加一段 content（不存在则创建，自动换行分隔）
- replace 用锚点精确替换：必须提供 old_text，在文件中**唯一**出现时替换为 new_text；
          缺失或出现多次会报错（防止误改）。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from mira import paths
from mira.core.tools.base import Tool, ToolContext, ToolResult, truncate_output

MEMORY_FILENAME = "memory.md"
_OPERATIONS = {"read", "append", "replace"}


def _memory_path(ctx: ToolContext) -> Path:
    """唯一记忆文件：workspace 数据目录下 memory.md。"""
    return paths.workspace_dir(ctx.workspace) / MEMORY_FILENAME


def _read_text(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


class ProjectMemoryTool(Tool):
    name = "project_memory"
    description = (
        "工作区级项目记忆：维护 ~/.mira-code/workspaces/<ws>/memory.md 单一记忆文件，"
        "供 agent 跨会话沉淀项目事实/约定/进度/教训（先 read 了解现状，再 append 或 replace 更新）。"
        "operation=read 读取全文；operation=append 在末尾追加 content；"
        "operation=replace 必须提供 old_text，把唯一出现的 old_text 替换为 content（缺失或多次出现会报错）。"
    )
    params_schema = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["read", "append", "replace"],
                "description": "read=读取 / append=末尾追加 / replace=锚点替换",
            },
            "content": {
                "type": "string",
                "description": "append 时追加的文本；replace 时的新文本（new_text）",
            },
            "old_text": {
                "type": "string",
                "description": "replace 时被替换的锚点（必填；须唯一出现，缺失或多次出现会报错）",
            },
        },
        "required": ["operation"],
    }

    def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
        op = args.get("operation")
        if op not in _OPERATIONS:
            return ToolResult(ok=False, error=f"非法操作: {op}（可用 read/append/replace）")
        t0 = time.perf_counter()
        path = _memory_path(ctx)
        try:
            if op == "read":
                return self._read(path, t0)
            if op == "append":
                return self._append(path, args.get("content", ""), t0)
            return self._replace(path, args.get("old_text", ""), args.get("content", ""), t0)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                ok=False,
                error=f"project_memory 失败: {exc}",
                duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            )

    # ── 操作实现 ─────────────────────────────────────────

    def _read(self, path: Path, t0: float) -> ToolResult:
        text = _read_text(path)
        if not text:
            out = "（尚无项目记忆，可用 operation=append 创建）"
            return ToolResult(ok=True, output=out, duration_ms=round((time.perf_counter() - t0) * 1000, 1))
        truncated, out = truncate_output(text)
        return ToolResult(
            ok=True, output=out, truncated=truncated,
            duration_ms=round((time.perf_counter() - t0) * 1000, 1),
        )

    def _append(self, path: Path, content: str, t0: float) -> ToolResult:
        content = content or ""
        if not content.strip():
            return ToolResult(ok=False, error="append 需要非空 content")
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = _read_text(path)
        sep = "" if not existing else ("" if existing.endswith("\n") else "\n")
        path.write_text(existing + sep + content + "\n", encoding="utf-8")
        lines = path.read_text(encoding="utf-8").count("\n")
        return ToolResult(
            ok=True,
            output=f"已追加 {len(content)} 字符（共 {lines} 行）到 {path}",
            duration_ms=round((time.perf_counter() - t0) * 1000, 1),
        )

    def _replace(self, path: Path, old_text: str, new_text: str, t0: float) -> ToolResult:
        if not old_text:
            return ToolResult(ok=False, error="replace 必须提供 old_text（要替换的锚点，不可省略）")
        text = _read_text(path)
        if not text:
            return ToolResult(ok=False, error="replace 锚点不存在：记忆文件为空（先 append 或整体覆盖）")
        count = text.count(old_text)
        if count == 0:
            return ToolResult(ok=False, error="replace 锚点不存在（old_text 未出现在记忆中）")
        if count > 1:
            return ToolResult(ok=False, error=f"replace 锚点出现 {count} 次，需更精确的 old_text")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.replace(old_text, new_text), encoding="utf-8")
        return ToolResult(
            ok=True,
            output=f"已替换 1 处（{len(old_text)} 字符 → {len(new_text)} 字符）",
            duration_ms=round((time.perf_counter() - t0) * 1000, 1),
        )
