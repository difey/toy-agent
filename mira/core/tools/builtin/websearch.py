"""内建工具：web_search — 通过 Exa AI 执行实时网络搜索。

参考 nano_claude.tools.websearch / exa_client：用 httpx 直接调 Exa 的 MCP 端点
（tools/call → web_search_exa），返回最相关网页的内容。可选 EXA_API_KEY 环境变量
（追加 ?exaApiKey=...）。
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx

from mira.core.tools.base import Tool, ToolContext, ToolResult, truncate_output

_EXA_URL = "https://mcp.exa.ai/mcp"
_EXA_TIMEOUT = 25.0  # Exa 调用自身超时（略小于 invoke 的 timeout_s）


def _call_exa(**opts: Any) -> str | None:
    """调 Exa MCP web_search_exa，返回首个文本内容；无内容返回 None。

    opts 直接作为 web_search_exa 的 arguments（须含 query）。
    注意签名不可有独立 query 参数——否则 query 会绑定到签名参数而不进 arguments。
    """
    url = _EXA_URL
    api_key = os.environ.get("EXA_API_KEY")
    if api_key:
        url += f"?exaApiKey={api_key}"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "web_search_exa", "arguments": opts},
    }
    resp = httpx.post(
        url,
        json=payload,
        headers={"Accept": "application/json, text/event-stream"},
        timeout=_EXA_TIMEOUT,
    )
    resp.raise_for_status()
    for line in resp.text.split("\n"):
        if not line.startswith("data: "):
            continue
        try:
            data = json.loads(line[6:])
        except json.JSONDecodeError:
            continue
        contents = data.get("result", {}).get("content", [])
        if contents and "text" in contents[0]:
            return contents[0]["text"]
    return None


class WebSearchTool(Tool):
    name = "web_search"
    timeout_s = 30.0  # invoke 层限时（Exa 自身超时 25s）
    description = (
        "通过 Exa AI 执行实时网络搜索，返回最相关网页的内容。"
        "用于获取训练截止之后的最新信息/实时数据。可配置返回结果数。"
    )
    # 注意：Exa MCP web_search_exa 的 schema 仅允许 query / numResults（additionalProperties=false），
    # 传入其它字段会整体校验失败
    params_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索查询"},
            "numResults": {"type": "integer", "description": "返回结果数（默认 8）"},
        },
        "required": ["query"],
    }

    def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
        query = str(args.get("query", "")).strip()
        if not query:
            return ToolResult(ok=False, error="缺少 query 参数")
        exa_args = {
            "query": query,
            "numResults": int(args.get("numResults") or 8),
        }
        t0 = time.perf_counter()
        try:
            # exa_args 已含 query，勿再传位置参数（否则 _call_exa() got multiple values for 'query'）
            result = _call_exa(**exa_args)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                ok=False,
                error=f"web_search 失败: {exc}",
                duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
        if not result:
            return ToolResult(
                ok=False,
                error="未找到搜索结果",
                duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
        truncated, output = truncate_output(result.strip())
        return ToolResult(
            ok=True,
            output=output,
            truncated=truncated,
            duration_ms=round((time.perf_counter() - t0) * 1000, 1),
        )
