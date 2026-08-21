"""McpManager：按会话管理 MCP 连接与工具（决策 #8d：随会话生命周期创建/释放）。

- 连接所有配置的 server；单个失败不影响其他（记录到 failed，工具被跳过）；
- 按 agent 的 `mcp.enabled` 集合暴露对应 server 的工具；
- 通过统一 Tool 接口接入内建 ToolRegistry，权限 / 遥测与内建一致（#8b）；
- 环境变量 `MIRA_MCP_DISABLED=1` 可整体关闭真实连接（测试 / 无网络环境）。
"""

from __future__ import annotations

import os

from mira.core.agents.base import BaseAgent
from mira.core.config.schemas import MCPServerConfig
from mira.core.mcp.base import McpError, McpTransport
from mira.core.mcp.bridge import McpTool
from mira.core.mcp.transports import make_transport
from mira.core.tools.base import Tool


class McpManager:
    def __init__(self, server_configs: dict[str, MCPServerConfig]) -> None:
        self._configs = server_configs
        self._transports: dict[str, McpTransport] = {}
        self._tools: dict[str, list[McpTool]] = {}
        self.failed: list[str] = []

    def connect_all(self) -> None:
        """连接所有配置的 server；失败逐个跳过（放入 failed）。"""
        if os.environ.get("MIRA_MCP_DISABLED") == "1":
            self.failed = list(self._configs)
            return
        for sid, cfg in self._configs.items():
            try:
                transport = make_transport(cfg)
                transport.initialize()
                tools = transport.list_tools()
                self._transports[sid] = transport
                self._tools[sid] = [
                    McpTool(
                        sid,
                        td.get("name", ""),
                        td.get("description", ""),
                        td.get("inputSchema", {}),
                        transport,
                    )
                    for td in tools
                    if td.get("name")
                ]
            except McpError:
                self.failed.append(sid)
            except Exception:  # noqa: BLE001
                self.failed.append(sid)

    def tools_for(self, agent: BaseAgent) -> list[Tool]:
        """该 agent 启用 server 的工具（连接成功者）。"""
        enabled = set(agent.config.mcp.enabled)
        out: list[Tool] = []
        for sid in sorted(enabled):
            out.extend(self._tools.get(sid, []))
        return out

    def is_connected(self, server_id: str) -> bool:
        return server_id in self._transports

    def close(self) -> None:
        for transport in self._transports.values():
            try:
                transport.close()
            except Exception:  # noqa: BLE001
                pass
        self._transports.clear()
        self._tools.clear()
        self.failed.clear()
