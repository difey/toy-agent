"""MCP 工具桥接：把 MCP server 暴露的工具包装为内建 Tool。

统一命名 `mcp_<server>_<tool>`（LLM provider 不支持 `.`）；统一权限（PermissionChecker）与遥测（tool.call/result/error）。
"""

from __future__ import annotations

import re
from typing import Any

from mira.core.mcp.base import McpTransport
from mira.core.tools.base import Tool, ToolContext, ToolResult


def _safe_name(name: str) -> str:
    """工具名清洗：只保留字母数字与 _ -（去掉 .，避免 LLM provider 不支持的字符）。"""
    return re.sub(r"[^A-Za-z0-9_-]", "_", name)


class McpTool(Tool):
    """包装一个 MCP 工具：run 时经 transport 调 `tools/call`。"""

    def __init__(
        self,
        server_id: str,
        mcp_tool_name: str,
        description: str,
        input_schema: dict[str, Any],
        transport: McpTransport,
    ) -> None:
        self.server_id = server_id
        self.mcp_tool_name = mcp_tool_name
        self.name = f"mcp_{server_id}_{_safe_name(mcp_tool_name)}"
        self.description = description or f"MCP 工具 {server_id}/{mcp_tool_name}"
        self.params_schema = input_schema or {"type": "object", "properties": {}}
        self._transport = transport

    def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
        try:
            result = self._transport.call_tool(self.mcp_tool_name, args)
            is_error = bool(result.get("isError"))
            text = "\n".join(
                c.get("text", "") for c in result.get("content", []) if isinstance(c, dict)
            )
            return ToolResult(ok=not is_error, output=text or "（MCP 返回空结果）")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"MCP 工具调用失败: {exc}")
