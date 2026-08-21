"""内建工具：search_grep 文本检索。"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from mira.core.tools.base import Tool, ToolContext, ToolResult, truncate_output

_SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".mira-code", ".idea", ".pytest_cache"}


class GrepTool(Tool):
    name = "search_grep"
    description = "在 workspace 内按正则检索文本文件，返回 文件:行号: 匹配行"
    params_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "正则表达式"},
            "path": {"type": "string", "description": "检索目录（默认 workspace 根）"},
            "glob": {"type": "string", "description": "文件通配（如 *.py，默认全部文本）"},
            "max_results": {"type": "integer", "description": "最多返回条数（默认 100）"},
        },
        "required": ["pattern"],
    }

    def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
        pattern = args["pattern"]
        root = ctx.resolve(args.get("path", "."))
        glob = args.get("glob") or "*"
        max_results = int(args.get("max_results") or 100)
        t0 = time.perf_counter()

        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return ToolResult(ok=False, error=f"正则无效: {exc}", duration_ms=0.0)

        hits: list[str] = []
        try:
            for path in sorted(root.rglob(glob)):
                if not path.is_file():
                    continue
                if any(part in _SKIP_DIRS for part in path.parts):
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except Exception:  # noqa: BLE001
                    continue
                for lineno, line in enumerate(text.splitlines(), 1):
                    if regex.search(line):
                        rel = path.relative_to(root)
                        hits.append(f"{rel}:{lineno}: {line.strip()[:200]}")
                        if len(hits) >= max_results:
                            break
                if len(hits) >= max_results:
                    break
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"检索失败: {exc}", duration_ms=0.0)

        elapsed = round((time.perf_counter() - t0) * 1000, 1)
        if not hits:
            return ToolResult(ok=True, output="未找到匹配", duration_ms=elapsed)
        truncated, output = truncate_output("\n".join(hits))
        return ToolResult(ok=True, output=output, duration_ms=elapsed, truncated=truncated)
