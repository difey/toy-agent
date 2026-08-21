"""MCP 传输实现：stdio（子进程，换行分隔 JSON-RPC 2.0）与 http（Streamable HTTP 简化）。"""

from __future__ import annotations

import json
import os
import select
import subprocess
import threading
import time
from typing import Any

import httpx

from mira.core.config.schemas import MCPServerConfig, MCPTransport as TransportKind
from mira.core.mcp.base import McpError, McpTransport

PROTOCOL_VERSION = "2024-11-05"


class StdioTransport(McpTransport):
    """通过子进程 stdio 与 MCP server 通信（换行分隔 JSON-RPC 2.0）。

    读响应带超时（select），避免 server 冷启动 / 无响应时无限阻塞。
    """

    def __init__(self, command: list[str], timeout: float = 15.0) -> None:
        self._proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._timeout = timeout
        self._id = 0
        self._lock = threading.Lock()

    def _read_line(self) -> str:
        deadline = time.monotonic() + self._timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise McpError("MCP 请求超时（server 无响应）")
            rlist, _, _ = select.select([self._proc.stdout], [], [], min(remaining, 5))
            if not rlist:
                continue
            line = self._proc.stdout.readline()
            if not line:
                raise McpError("MCP server 意外退出")
            return line

    def _request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            self._id += 1
            rid = self._id
            self._proc.stdin.write(
                json.dumps(
                    {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
                )
                + "\n"
            )
            self._proc.stdin.flush()
            while True:
                line = self._read_line().strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("id") != rid:
                    continue  # 跳过通知 / 其它请求的响应
                if "error" in msg:
                    raise McpError(msg["error"].get("message", "mcp error"))
                return msg.get("result") or {}

    def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._proc.stdin.write(
            json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}}) + "\n"
        )
        self._proc.stdin.flush()

    def initialize(self) -> dict[str, Any]:
        res = self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mira", "version": "0.1"},
            },
        )
        self._notify("notifications/initialized")
        return res

    def list_tools(self) -> list[dict[str, Any]]:
        res = self._request("tools/list")
        return res.get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._request("tools/call", {"name": name, "arguments": arguments or {}})

    def close(self) -> None:
        try:
            self._proc.terminate()
        except Exception:  # noqa: BLE001
            pass


class HttpTransport(McpTransport):
    """MCP Streamable HTTP 简化客户端：POST JSON-RPC，解析 JSON 或 SSE 首条 data。"""

    def __init__(self, url: str, auth_ref: str | None = None, timeout: float = 30.0) -> None:
        self.url = url
        self.auth = os.environ.get(auth_ref) if auth_ref else None
        self._timeout = timeout
        self._id = 0
        self._session_id: str | None = None

    def _request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._id += 1
        body = {
            "jsonrpc": "2.0",
            "id": self._id,
            "method": method,
            "params": params or {},
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        if self.auth:
            headers["Authorization"] = f"Bearer {self.auth}"
        try:
            resp = httpx.post(self.url, json=body, headers=headers, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise McpError(f"MCP http 请求失败: {exc}") from exc
        sid = resp.headers.get("mcp-session-id")
        if sid:
            self._session_id = sid
        text = resp.text
        if "text/event-stream" in resp.headers.get("content-type", ""):
            data = self._parse_sse(text)
            msg = json.loads(data) if data else {"result": {}}
        else:
            msg = json.loads(text) if text else {"result": {}}
        if msg.get("error"):
            raise McpError(msg["error"].get("message", "mcp error"))
        return msg.get("result") or {}

    @staticmethod
    def _parse_sse(text: str) -> str:
        data: list[str] = []
        for block in text.split("\n\n"):
            for line in block.splitlines():
                if line.startswith("data:"):
                    d = line[5:].strip()
                    if d and d != "[DONE]":
                        data.append(d)
        return "".join(data)

    def initialize(self) -> dict[str, Any]:
        return self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mira", "version": "0.1"},
            },
        )

    def list_tools(self) -> list[dict[str, Any]]:
        res = self._request("tools/list")
        return res.get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._request("tools/call", {"name": name, "arguments": arguments or {}})

    def close(self) -> None:
        pass


def make_transport(cfg: MCPServerConfig) -> McpTransport:
    """按配置构造传输层。"""
    if cfg.transport == TransportKind.STDIO:
        if not cfg.command:
            raise McpError(f"MCP server {cfg.id!r} 缺少 stdio command")
        return StdioTransport(list(cfg.command))
    if cfg.transport == TransportKind.HTTP:
        if not cfg.url:
            raise McpError(f"MCP server {cfg.id!r} 缺少 http url")
        return HttpTransport(cfg.url, cfg.auth)
    raise McpError(f"不支持的 MCP 传输: {cfg.transport}")
