"""MCP 抽象：传输层接口与错误类型。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class McpError(Exception):
    """MCP 通信 / 协议错误。"""


class McpTransport(ABC):
    """MCP 传输层抽象：JSON-RPC 2.0 请求 / 响应（initialize → tools/list → tools/call）。"""

    @abstractmethod
    def initialize(self) -> dict[str, Any]:
        """握手：initialize + initialized 通知，返回 server 信息。"""

    @abstractmethod
    def list_tools(self) -> list[dict[str, Any]]:
        """枚举 server 暴露的工具定义。"""

    @abstractmethod
    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """调用工具，返回 MCP 结果（含 content / isError）。"""

    @abstractmethod
    def close(self) -> None:
        """释放连接 / 终止进程。"""
