#!/usr/bin/env python3
"""最小 MCP stdio server（测试用）：换行分隔 JSON-RPC 2.0。

处理：initialize / notifications/initialized / tools/list / tools/call（echo / add）。
"""

import json
import sys

TOOLS = [
    {
        "name": "echo",
        "description": "回显一段文本",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "add",
        "description": "两个数相加",
        "inputSchema": {
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
        },
    },
]


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = msg.get("id")
        method = msg.get("method")
        params = msg.get("params") or {}

        if method == "initialize":
            result = {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {},
                "serverInfo": {"name": "mock-mcp", "version": "1.0"},
            }
        elif method == "notifications/initialized":
            continue  # 通知：无响应
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            if name == "echo":
                result = {"content": [{"type": "text", "text": f"echo:{args.get('text', '')}"}]}
            elif name == "add":
                result = {
                    "content": [{"type": "text", "text": str(args.get("a", 0) + args.get("b", 0))}]
                }
            else:
                result = {"content": [], "isError": True}
        else:
            result = {}

        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
