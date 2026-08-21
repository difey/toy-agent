"""内建工具：glob — 按 glob 模式在 workspace 内快速查找文件路径。

参考 nano_claude.tools.glob_，适配 Mira 的 Tool.run / ToolResult / workspace 路径。
"""

from __future__ import annotations

import glob
import os
import time
from typing import Any

from mira.core.tools.base import Tool, ToolContext, ToolResult, truncate_output


class GlobTool(Tool):
    name = "glob"
    description = "按 glob 模式在 workspace 内查找文件路径（如 **/*.py 或 src/**/*.ts），按修改时间倒序返回"
    params_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "glob 模式，如 **/*.py"},
            "path": {"type": "string", "description": "检索目录（默认 workspace 根）"},
            "max_results": {"type": "integer", "description": "最多返回条数（默认 200）"},
        },
        "required": ["pattern"],
    }

    def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
        pattern = args.get("pattern", "")
        if not pattern:
            return ToolResult(ok=False, error="缺少 pattern 参数")
        root = ctx.resolve(args.get("path", "."))
        max_results = int(args.get("max_results") or 200)
        if not root.is_dir():
            return ToolResult(ok=False, error=f"目录不存在: {root}")

        t0 = time.perf_counter()
        try:
            matches = sorted(
                glob.glob(str(root / pattern), recursive=True),
                key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0,
                reverse=True,
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"glob 失败: {exc}")

        if not matches:
            output = "(no matches)"
        else:
            rel = [os.path.relpath(m, root) for m in matches[:max_results]]
            output = "\n".join(rel)
            if len(matches) > max_results:
                output += f"\n…（共 {len(matches)} 条，显示前 {max_results}）"
        truncated, output = truncate_output(output)
        return ToolResult(
            ok=True,
            output=output,
            truncated=truncated,
            duration_ms=round((time.perf_counter() - t0) * 1000, 1),
        )
