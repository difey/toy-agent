"""内建工具：文件读取 / 写入 / 编辑。"""

from __future__ import annotations

import time
from typing import Any

from mira.core.tools.base import Tool, ToolContext, ToolResult, truncate_output


class FileReadTool(Tool):
    name = "file_read"
    description = "读取文件内容（相对 workspace 路径），每次最多 1000 行；可用 start 指定起始行、limit 限制行数"
    params_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径（相对 workspace）"},
            "start": {"type": "integer", "description": "从第几行开始读取（1 起，默认 1）"},
            "limit": {"type": "integer", "description": "最多读取行数（默认 1000，上限 1000）"},
        },
        "required": ["path"],
    }

    MAX_LINES = 1000  # 单次读取行数硬上限

    def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
        path = ctx.resolve(args["path"])
        t0 = time.perf_counter()
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ToolResult(ok=False, error=f"文件不存在: {path}", duration_ms=0.0)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"读取失败: {exc}", duration_ms=0.0)

        # start：从第几行开始读取（1 起，默认 1）；offset 为旧参数兼容别名
        start = int(args.get("start") or args.get("offset") or 1)
        if start < 1:
            start = 1
        limit = int(args.get("limit") or self.MAX_LINES)
        if limit < 1:
            limit = self.MAX_LINES
        limit = min(limit, self.MAX_LINES)  # 硬上限：单次最多 1000 行

        lines = text.splitlines(keepends=True)
        total = len(lines)
        if start > total:
            return ToolResult(
                ok=False,
                error=f"start={start} 超出文件总行数（共 {total} 行）",
                duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
        end = min(start - 1 + limit, total)
        chunk = lines[start - 1 : end]
        skipped = total - end  # 因 1000 行上限被略过的剩余行数
        chunk_truncated, chunk_text = truncate_output("".join(chunk))
        note = ""
        if skipped > 0:
            note = f"\n… 后面共 {skipped} 行被略过（最多显示 {self.MAX_LINES} 行；可用 start 从其它位置继续读取）"
        return ToolResult(
            ok=True,
            output=chunk_text + note,
            duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            truncated=chunk_truncated or skipped > 0,
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
