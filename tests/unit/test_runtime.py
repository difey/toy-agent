"""P1：AgentRuntime 执行循环单测（工具循环 / 权限 / 历史 / 事件）。"""

import json
from pathlib import Path

from mira.core.agents.base import BaseAgent
from mira.core.config.schemas import (
    AgentConfig,
    AgentRole,
    AgentToolsConfig,
    ApprovalMode,
    PermissionRule,
)
from mira.core.providers.base import ChatMessage, ChatRole
from mira.core.providers.mock import MockProvider
from mira.core.providers.router import ProviderRouter
from mira.core.runtime import AgentRuntime
from mira.core.tools.permission import PermissionChecker
from mira.core.tools.registry import ToolRegistry
from mira.telemetry.events import EventType
from mira.telemetry.store import EventStore
from mira.telemetry.tracer import EventLogTracer


def _tool_call(name: str, args: dict, call_id: str = "c1") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def _make_runtime(
    tmp_path: Path,
    tracer: EventLogTracer,
    *,
    tool_calls=None,
    reply: str = "已完成",
    reasoning: str | None = None,
    rules: list[PermissionRule] | None = None,
    mode: ApprovalMode = ApprovalMode.AUTO,
    approvals=None,
    auto_approver=None,
):
    agent = AgentConfig(
        id="main",
        role=AgentRole.MAIN,
        system_prompt="你是测试助手。",
        model="mock/mock-model",
        tools=AgentToolsConfig(enabled=["file_write", "file_read", "shell"]),
    )
    router = ProviderRouter(
        [MockProvider(id="mock", reply=reply, tool_calls=tool_calls, reasoning=reasoning)]
    )
    return AgentRuntime(
        agent=BaseAgent(agent),
        router=router,
        tools=ToolRegistry.with_builtins(),
        permissions=PermissionChecker(rules, mode=mode),
        tracer=tracer,
        workspace=tmp_path,
        max_steps=5,
        approvals=approvals,
        auto_approver=auto_approver,
    )


def test_runtime_writes_file_via_tool(tmp_path):
    tracer = EventLogTracer(EventStore(tmp_path / "sessions"))
    rt = _make_runtime(
        tmp_path,
        tracer,
        tool_calls=[_tool_call("file_write", {"path": "hello.txt", "content": "hi"})],
        reply="已写入文件",
    )
    reply = rt.run("请创建 hello.txt", "sess_1")
    assert reply == "已写入文件"
    assert (tmp_path / "hello.txt").read_text() == "hi"

    events = list(EventStore(tmp_path / "sessions").read("sess_1"))
    types = [e.type for e in events]
    assert EventType.TOOL_CALL in types
    assert EventType.TOOL_RESULT in types
    assert EventType.AGENT_MESSAGE in types
    assert EventType.AGENT_LOOP_END in types

    # 工具调用与 LLM 同属一次运行 span 树
    llm = next(e for e in events if e.type == EventType.LLM_REQUEST)
    tool = next(e for e in events if e.type == EventType.TOOL_CALL)
    assert tool.parent_span_id == llm.parent_span_id
    # 事件落盘（session 文件夹 + session_id.jsonl）
    assert (tmp_path / "sessions" / "sess_1" / "session_id.jsonl").exists()


def test_reasoning_content_preserved_in_history(tmp_path):
    """DeepSeek thinking：reasoning_content 从流中累积并保留到历史（多轮需回传）。"""
    tracer = EventLogTracer(EventStore(tmp_path / "sessions"))
    rt = _make_runtime(tmp_path, tracer, reply="结论", reasoning="推理链 A...")
    rt.run("你好", "sess_r1")

    assistants = [m for m in rt.history if m.role == ChatRole.ASSISTANT]
    assert assistants
    assert assistants[-1].reasoning_content == "推理链 A..."
    api = assistants[-1].to_api()
    assert api["reasoning_content"] == "推理链 A..."  # litellm 据此避免占位符警告

    # 事件也记录推理链（供观测）
    resp = next(
        e for e in EventStore(tmp_path / "sessions").read("sess_r1") if e.type == EventType.LLM_RESPONSE
    )
    assert resp.payload.get("reasoning_content") == "推理链 A..."


def test_runtime_denied_tool_not_executed(tmp_path):
    tracer = EventLogTracer(EventStore(tmp_path / "sessions"))
    rules = [PermissionRule(tool="file_write", path="**", action="deny")]
    rt = _make_runtime(
        tmp_path,
        tracer,
        tool_calls=[_tool_call("file_write", {"path": "x.txt", "content": "x"})],
        rules=rules,
    )
    rt.run("写文件", "sess_1")
    assert not (tmp_path / "x.txt").exists()
    events = list(EventStore(tmp_path / "sessions").read("sess_1"))
    assert any(e.type == EventType.TOOL_ERROR for e in events)
    denied = next(e for e in events if e.type == EventType.TOOL_ERROR)
    assert "denied" in (denied.payload.get("error") or "")


def test_runtime_ask_auto_approves(tmp_path):
    tracer = EventLogTracer(EventStore(tmp_path / "sessions"))
    rules = [PermissionRule(tool="shell_*", path="**", action="ask")]
    rt = _make_runtime(
        tmp_path,
        tracer,
        tool_calls=[_tool_call("shell", {"cmd": "echo ok"})],
        rules=rules,
        mode=ApprovalMode.ASK,
    )
    rt.run("跑个命令", "sess_1")
    types = [e.type for e in EventStore(tmp_path / "sessions").read("sess_1")]
    assert EventType.APPROVAL_REQUESTED in types
    assert EventType.APPROVAL_RESOLVED in types
    assert EventType.TOOL_RESULT in types


def test_runtime_auto_approver_allows(tmp_path):
    """自动审批：决策器返回 allow → 工具执行，无人工审批挂起。"""
    from mira.api.approval import ApprovalDecision, ApprovalGate

    tracer = EventLogTracer(EventStore(tmp_path / "sessions"))
    rules = [PermissionRule(tool="file_write", path="**", action="ask")]
    gate = ApprovalGate("sess_1")
    rt = _make_runtime(
        tmp_path,
        tracer,
        tool_calls=[_tool_call("file_write", {"path": "ok.txt", "content": "ok"})],
        rules=rules,
        mode=ApprovalMode.ASK,
        approvals=gate,
        auto_approver=lambda name, args, path: ApprovalDecision.ALLOW,
    )
    rt.run("写文件", "sess_1")
    assert (tmp_path / "ok.txt").read_text() == "ok"
    assert not gate.pending()


def test_runtime_auto_approver_denies(tmp_path):
    """自动审批：决策器返回 deny → 工具被拒，历史回填审批拒绝错误。"""
    from mira.api.approval import ApprovalDecision, ApprovalGate

    tracer = EventLogTracer(EventStore(tmp_path / "sessions"))
    rules = [PermissionRule(tool="file_write", path="**", action="ask")]
    gate = ApprovalGate("sess_1")
    rt = _make_runtime(
        tmp_path,
        tracer,
        tool_calls=[_tool_call("file_write", {"path": "x.txt", "content": "x"})],
        rules=rules,
        mode=ApprovalMode.ASK,
        approvals=gate,
        auto_approver=lambda name, args, path: ApprovalDecision.DENY,
    )
    rt.run("写文件", "sess_1")
    assert not (tmp_path / "x.txt").exists()
    assert any(
        m.role == ChatRole.TOOL and "approval denied" in m.content for m in rt.history
    )


def test_runtime_auto_approver_fallback_to_human(tmp_path):
    """自动审批：决策器返回 None（无法判断）→ 回退人工审批，阻塞等待决议。"""
    import threading
    import time

    from mira.api.approval import ApprovalGate

    tracer = EventLogTracer(EventStore(tmp_path / "sessions"))
    rules = [PermissionRule(tool="file_write", path="**", action="ask")]
    gate = ApprovalGate("sess_1")
    rt = _make_runtime(
        tmp_path,
        tracer,
        tool_calls=[_tool_call("file_write", {"path": "h.txt", "content": "h"})],
        rules=rules,
        mode=ApprovalMode.ASK,
        approvals=gate,
        auto_approver=lambda name, args, path: None,  # 无法判断 → 回退人工
    )
    result: dict = {}
    th = threading.Thread(
        target=lambda: result.setdefault("reply", rt.run("写文件", "sess_1"))
    )
    th.start()
    for _ in range(100):
        if gate.pending():
            break
        time.sleep(0.02)
    assert gate.pending()  # 已回退到人工审批
    gate.resolve(gate.pending()[0].id, "allow")
    th.join(timeout=3)
    assert not th.is_alive()
    assert (tmp_path / "h.txt").read_text() == "h"


def test_runtime_history_accumulates(tmp_path):
    tracer = EventLogTracer(EventStore(tmp_path / "sessions"))
    rt = _make_runtime(tmp_path, tracer, reply="第一轮")
    assert rt.run("你好", "sess_1") == "第一轮"
    assert rt.run("再说一遍", "sess_1") == "第一轮"
    assert len(rt.history) == 4  # 2 user + 2 assistant
    assert rt.history[0].role == ChatRole.USER


def test_runtime_tool_arg_parse_error_fed_back(tmp_path):
    """LLM 生成非合法 JSON 参数：解析错误回填 TOOL 历史，AI 看到后可修正后重试。"""
    tracer = EventLogTracer(EventStore(tmp_path / "sessions"))
    call = {
        "id": "c9",
        "type": "function",
        "function": {"name": "file_write", "arguments": "{invalid json"},
    }
    rt = _make_runtime(tmp_path, tracer, tool_calls=[call], reply="参数有误，已修正")
    reply = rt.run("写文件", "sess_1")
    # 工具错误回填后，第二轮 AI 给出最终回复
    assert reply == "参数有误，已修正"
    tool_msgs = [m for m in rt.history if m.role == ChatRole.TOOL]
    assert tool_msgs
    assert "参数解析失败" in tool_msgs[0].content
    assert tool_msgs[0].tool_call_id == "c9"
    events = list(EventStore(tmp_path / "sessions").read("sess_1"))
    assert any(e.type == EventType.TOOL_ERROR for e in events)
    err = next(e for e in events if e.type == EventType.TOOL_ERROR)
    assert "参数解析失败" in (err.payload.get("error") or "")


def test_runtime_extra_history_prepended(tmp_path):
    """附件文件：extra_history 作为前导 user 消息，与 user_text 同轮发送给 AI。"""
    tracer = EventLogTracer(EventStore(tmp_path / "sessions"))
    rt = _make_runtime(tmp_path, tracer, reply="已看到文件")
    extra = [ChatMessage(role=ChatRole.USER, content="用户选中了文件：\n/tmp/a.py")]
    assert rt.run("请分析这个文件", "sess_1", extra_history=extra) == "已看到文件"
    users = [m for m in rt.history if m.role == ChatRole.USER]
    assert len(users) == 2
    assert users[0].content == "用户选中了文件：\n/tmp/a.py"
    assert users[1].content == "请分析这个文件"
