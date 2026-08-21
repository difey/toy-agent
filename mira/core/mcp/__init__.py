"""MCP 桥接：把 MCP server 暴露的工具接入内建工具体系（P3）。

决策 #8a–8d：
- 8a 凭据配置明文（接口预留 env ref 升级）；
- 8b MCP 工具权限与内建工具统一 allow / deny / ask；
- 8c 信任本地配置，不沙箱；
- 8d 连接按会话独立创建 / 释放（见 McpManager）。
"""

from mira.core.mcp.base import McpError, McpTransport
from mira.core.mcp.bridge import McpTool
from mira.core.mcp.manager import McpManager
from mira.core.mcp.transports import HttpTransport, StdioTransport, make_transport

__all__ = [
    "McpError",
    "McpTransport",
    "McpTool",
    "McpManager",
    "StdioTransport",
    "HttpTransport",
    "make_transport",
]
