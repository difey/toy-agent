"""内建工具：文件读取 / 写入 / 编辑。"""

from __future__ import annotations

import time
from typing import Any

from mira.core.tools.base import Tool, ToolContext, ToolResult, truncate_output


class FileReadTool(Tool):
    name = "file_read"
    description = "读取文件内容（相对 workspace 路径），可指定行范围"
    params_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径（相对 workspace）"},
            "offset": {"type": "integer", "description": "起始行（1 起，默认全部）"},
            "limit": {"type": "integer", "description": "最多读取行数"},
        },
        "required": ["path"],
    }

    def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
        path = ctx.resolve(args["path"])
        t0 = time.perf_counter()
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ToolResult(ok=False, error=f"文件不存在: {path}", duration_ms=0.0)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"读取失败: {exc}", duration_ms=0.0)

        offset = int(args.get("offset") or 1)
        limit = int(args.get("limit") or 0)
        lines = text.splitlines(keepends=True)
        if offset > 1 or limit:
            lines = lines[offset - 1 : offset - 1 + limit] if limit else lines[offset - 1 :]
        truncated, output = truncate_output("".join(lines))
        return ToolResult(
            ok=True,
            output=output,
            duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            truncated=truncated,
        )


class FileWriteTool(Tool):
    name = "file_write"
    description = "写入 / 覆盖文件内容（自动创建父目录）"
    params_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径（相对 workspace）"},
            "content": {"type": "string", "description": "要写入的内容"},
        },
        "required": ["path", "content"],
    }

    def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
        path = ctx.resolve(args["path"])
        content = str(args.get("content", ""))
        t0 = time.perf_counter()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                ok=False, error=f"写入失败: {exc}",
                duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
        return ToolResult(
            ok=True,
            output=f"已写入 {path}（{len(content)} 字符）",
            duration_ms=round((time.perf_counter() - t0) * 1000, 1),
        )


class FileEditTool(Tool):
    name = "file_edit"
    description = "在文件中将一段精确文本替换为另一段（锚点唯一，否则报错）"
    params_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径（相对 workspace）"},
            "old": {"type": "string", "description": "要替换的原文（锚点）"},
            "new": {"type": "string", "description": "替换后的文本"},
        },
        "required": ["path", "old", "new"],
    }

    def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
        path = ctx.resolve(args["path"])
        old, new = args["old"], args["new"]
        t0 = time.perf_counter()
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ToolResult(ok=False, error=f"文件不存在: {path}", duration_ms=0.0)
        count = text.count(old)
        if count == 0:
            return ToolResult(
                ok=False,
                error=f"锚点未找到: {old[:120]!r}",
                duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
        if count > 1:
            return ToolResult(
                ok=False,
                error=f"锚点出现 {count} 次，需更精确",
                duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
        return ToolResult(
            ok=True,
            output=f"已编辑 {path}",
            duration_ms=round((time.perf_counter() - t0) * 1000, 1),
        )
