"""内建工具：shell 命令执行。"""

from __future__ import annotations

import subprocess
import time
from typing import Any

from mira.core.tools.base import Tool, ToolContext, ToolResult, truncate_output


class ShellTool(Tool):
    name = "shell"
    timeout_s = 60  # 默认命令超时 60s（类级配置，经 invoke 生效）
    description = "在 workspace 中执行 shell 命令并返回输出（捕获 stdout/stderr，超时 60s）"
    params_schema = {
        "type": "object",
        "properties": {
            "cmd": {"type": "string", "description": "要执行的 shell 命令"}
        },
        "required": ["cmd"],
    }

    def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
        cmd = args.get("cmd", "")
        if not isinstance(cmd, str) or not cmd.strip():
            return ToolResult(ok=False, error="缺少 cmd 参数")

        t0 = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                cwd=str(ctx.workspace),
                capture_output=True,
                text=True,
                timeout=self.timeout_s if self.timeout_s > 0 else None,
            )
        except subprocess.TimeoutExpired as exc:
            out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            return ToolResult(
                ok=False,
                error=f"shell 命令超时（{self.timeout_s:g}s）",
                output=truncate_output(out)[1],
                duration_ms=(time.perf_counter() - t0) * 1000,
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                ok=False,
                error=f"shell 执行失败: {exc}",
                duration_ms=(time.perf_counter() - t0) * 1000,
            )

        elapsed = (time.perf_counter() - t0) * 1000
        combined = (proc.stdout or "") + (proc.stderr or "")
        truncated, output = truncate_output(combined.strip())
        ok = proc.returncode == 0
        return ToolResult(
            ok=ok,
            output=output,
            error=None if ok else f"exit={proc.returncode}",
            duration_ms=round(elapsed, 1),
            truncated=truncated,
        )
