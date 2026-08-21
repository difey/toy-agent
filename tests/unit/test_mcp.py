"""P3：MCP 桥接单测（stdio server / 注册表 / 权限 / 遥测 / 容错）。"""

import json
import sys
from pathlib import Path

import pytest

from mira.core.agents.base import BaseAgent
from mira.core.config.schemas import (
    AgentConfig,
    AgentMcpConfig,
    AgentRole,
    AgentToolsConfig,
    ApprovalMode,
    MCPServerConfig,
    MCPTransport,
)
from mira.core.mcp.manager import McpManager
from mira.core.providers.mock import MockProvider
from mira.core.providers.router import ProviderRouter
from mira.core.runtime import AgentRuntime
from mira.core.tools.base import ToolContext
from mira.core.tools.permission import PermissionChecker
from mira.core.tools.registry import ToolRegistry
from mira.telemetry.events import EventType
from mira.telemetry.store import EventStore
from mira.telemetry.tracer import EventLogTracer

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "mcp_echo_server.py"


@pytest.fixture(autouse=True)
def _enable_mcp(monkeypatch):
    """恢复真实 MCP 连接（本模块使用自建 mock stdio server）。"""
    monkeypatch.delenv("MIRA_MCP_DISABLED", raising=False)
    yield


def _server(id: str = "mock") -> MCPServerConfig:
    return MCPServerConfig(
        id=id, transport=MCPTransport.STDIO, command=[sys.executable, str(FIXTURE)]
    )


def _agent_with_mcp(server_id: str = "mock") -> BaseAgent:
    cfg = AgentConfig(
        id="main", role=AgentRole.MAIN, mcp=AgentMcpConfig(enabled=[server_id])
    )
    return BaseAgent(cfg)


def test_mcp_manager_list_and_call():
    mgr = McpManager({"mock": _server()})
    mgr.connect_all()
    assert mgr.is_connected("mock")
    tools = mgr.tools_for(_agent_with_mcp())
    assert {t.name for t in tools} == {"mcp_mock_echo", "mcp_mock_add"}

    echo = next(t for t in tools if t.name == "mcp_mock_echo")
    r = echo.run(ToolContext(workspace="."), text="hello")
    assert r.ok and "echo:hello" in r.output

    add = next(t for t in tools if t.name == "mcp_mock_add")
    r2 = add.run(ToolContext(workspace="."), a=2, b=3)
    assert r2.ok and r2.output.strip() == "5"
    mgr.close()
    assert not mgr.is_connected("mock")


def test_mcp_tools_share_registry_permission_telemetry(tmp_path):
    mgr = McpManager({"mock": _server()})
    mgr.connect_all()
    agent = _agent_with_mcp()
    tools = ToolRegistry.with_builtins()
    for t in mgr.tools_for(agent):
        tools.register(t)

    call = {
        "id": "c1",
        "type": "function",
        "function": {"name": "mcp_mock_echo", "arguments": json.dumps({"text": "hi"})},
    }
    cfg = AgentConfig(
        id="main",
        role=AgentRole.MAIN,
        system_prompt="测试",
        model="mock/m",
        tools=AgentToolsConfig(enabled=["mcp_mock_echo"]),
        mcp=AgentMcpConfig(enabled=["mock"]),
    )
    tracer = EventLogTracer(EventStore(tmp_path / "sessions"))
    rt = AgentRuntime(
        agent=BaseAgent(cfg),
        router=ProviderRouter([MockProvider(id="mock", reply="ok", tool_calls=[call])]),
        tools=tools,
        permissions=PermissionChecker([], mode=ApprovalMode.AUTO),
        tracer=tracer,
        workspace=tmp_path,
        tools_override=["mcp_mock_echo"],
    )
    rt.run("echo hi", "s1")

    events = list(EventStore(tmp_path / "sessions").read("s1"))
    types = [e.type for e in events]
    assert EventType.TOOL_CALL in types
    assert EventType.TOOL_RESULT in types
    tool_result = next(e for e in events if e.type == EventType.TOOL_RESULT)
    assert "echo:hi" in (tool_result.payload.get("result") or "")
    # MCP 工具名出现在 LLM 工具描述中
    llm = next(e for e in events if e.type == EventType.LLM_REQUEST)
    assert "mcp_mock_echo" in llm.payload.get("tools", [])
    mgr.close()


def test_mcp_manager_skips_unreachable():
    servers = {
        "gh": MCPServerConfig(
            id="gh", transport=MCPTransport.HTTP, url="http://127.0.0.1:1/mcp"
        )
    }
    mgr = McpManager(servers)
    mgr.connect_all()
    assert "gh" in mgr.failed
    assert not mgr.is_connected("gh")
    assert mgr.tools_for(_agent_with_mcp("gh")) == []
    mgr.close()
