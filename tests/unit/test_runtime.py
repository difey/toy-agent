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
from mira.core.skills.base import Skill
from mira.core.skills.registry import SkillRegistry
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
    # call_id（tool_call_id）写入遥测：tool.call / tool.result 事件均带，供前端精确配对
    tr = next(e for e in events if e.type == EventType.TOOL_RESULT)
    assert tool.payload.get("call_id") == "c1"
    assert tr.payload.get("call_id") == "c1"
    # 事件落盘（session 文件夹 + session_id.jsonl）
    assert (tmp_path / "sessions" / "sess_1" / "session_id.jsonl").exists()


def test_runtime_skill_tool_returns_full_text(tmp_path):
    """skill 工具：runtime 的 skill_lookup 钩子把技能全文作为 tool result 返回给 LLM。"""
    skills = SkillRegistry().register(
        Skill(id="planning", name="planning", description="计划", prompt="请先制定分步计划再执行。")
    )
    tracer = EventLogTracer(EventStore(tmp_path / "sessions"))
    agent = AgentConfig(
        id="main",
        role=AgentRole.MAIN,
        system_prompt="你是助手。",
        model="mock/mock-model",
        tools=AgentToolsConfig(enabled=["skill"]),
    )
    router = ProviderRouter(
        [
            MockProvider(
                id="mock",
                reply="已按计划执行",
                tool_calls=[_tool_call("skill", {"name": "planning"})],
            )
        ]
    )
    rt = AgentRuntime(
        agent=BaseAgent(agent),
        router=router,
        tools=ToolRegistry.with_builtins(),
        permissions=PermissionChecker([], mode=ApprovalMode.AUTO),
        tracer=tracer,
        workspace=tmp_path,
        skills=skills,
        max_steps=5,
    )
    reply = rt.run("规划一下", "sess_skill")
    assert reply == "已按计划执行"
    events = list(EventStore(tmp_path / "sessions").read("sess_skill"))
    tr = next(e for e in events if e.type == EventType.TOOL_RESULT)
    assert "请先制定分步计划再执行" in tr.payload["result"]  # 全文作为 tool result 发给 LLM
    # skill 工具在 LLM 请求的 tool_specs 中可见
    req = next(e for e in events if e.type == EventType.LLM_REQUEST)
    schema_names = [s["function"]["name"] for s in req.payload["tools_schema"]]
    assert "skill" in schema_names


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


def test_repair_tool_call_integrity_drops_dangling_call():
    """故障导致 a/b 有结果、c 缺失：把 c 从 assistant 的 tool_calls 中删除。"""
    from mira.core.context import repair_tool_call_integrity

    def tc(cid):
        return {"id": cid, "type": "function", "function": {"name": "file_write", "arguments": "{}"}}

    h = [
        ChatMessage(role=ChatRole.USER, content="改文件"),
        ChatMessage(role=ChatRole.ASSISTANT, content="", tool_calls=[tc("a"), tc("b"), tc("c")]),
        ChatMessage(role=ChatRole.TOOL, content="ok a", tool_call_id="a"),
        ChatMessage(role=ChatRole.TOOL, content="ok b", tool_call_id="b"),
    ]
    repair_tool_call_integrity(h)
    assert [c["id"] for c in h[1].tool_calls] == ["a", "b"]


def test_repair_tool_call_integrity_keeps_complete():
    """所有 tool_call 都有结果 → 历史不被改动。"""
    from mira.core.context import repair_tool_call_integrity

    def tc(cid):
        return {"id": cid, "type": "function", "function": {"name": "file_write", "arguments": "{}"}}

    h = [
        ChatMessage(role=ChatRole.USER, content="改文件"),
        ChatMessage(role=ChatRole.ASSISTANT, content="", tool_calls=[tc("a"), tc("b"), tc("c")]),
        ChatMessage(role=ChatRole.TOOL, content="ok", tool_call_id="a"),
        ChatMessage(role=ChatRole.TOOL, content="ok", tool_call_id="b"),
        ChatMessage(role=ChatRole.TOOL, content="ok", tool_call_id="c"),
    ]
    repair_tool_call_integrity(h)
    assert [c["id"] for c in h[1].tool_calls] == ["a", "b", "c"]


def test_repair_tool_call_integrity_fixes_complete_record():
    """修复完整记录：整段历史（不只上一条用户消息之后）所有悬空 call 都被删除。"""
    from mira.core.context import repair_tool_call_integrity

    def tc(cid):
        return {"id": cid, "type": "function", "function": {"name": "file_write", "arguments": "{}"}}

    h = [
        ChatMessage(role=ChatRole.USER, content="第一轮"),
        ChatMessage(role=ChatRole.ASSISTANT, content="", tool_calls=[tc("x")]),  # x 无结果（旧段）
        ChatMessage(role=ChatRole.USER, content="第二轮"),
        ChatMessage(role=ChatRole.ASSISTANT, content="", tool_calls=[tc("a"), tc("b")]),
        ChatMessage(role=ChatRole.TOOL, content="ok a", tool_call_id="a"),  # b 结果缺失（当前段）
    ]
    repair_tool_call_integrity(h)
    assert h[1].tool_calls is None  # 旧段悬空 call 也被删除
    assert [c["id"] for c in h[3].tool_calls] == ["a"]  # 当前段删掉无结果的 b


def test_runtime_request_repairs_dangling_tool_call(tmp_path):
    """runtime 发请求前（build_context）修复历史中悬空的 tool_call。"""
    tracer = EventLogTracer(EventStore(tmp_path / "sessions"))
    rt = _make_runtime(tmp_path, tracer, reply="继续")
    # 模拟故障历史：assistant 声明 a、c，但只有 a 有结果
    rt.history.append(ChatMessage(role=ChatRole.USER, content="先删再写"))
    rt.history.append(
        ChatMessage(
            role=ChatRole.ASSISTANT,
            content="",
            tool_calls=[
                {"id": "a", "type": "function", "function": {"name": "file_write", "arguments": '{"path":"1.txt","content":"1"}'}},
                {"id": "c", "type": "function", "function": {"name": "file_write", "arguments": '{"path":"2.txt","content":"2"}'}},
            ],
        )
    )
    rt.history.append(ChatMessage(role=ChatRole.TOOL, content="ok a", tool_call_id="a"))

    assert rt.run("继续", "sess_1") == "继续"
    # 请求前修复生效：assistant 的 tool_calls 只剩有结果的 a，c 已被删除
    asst = next(m for m in rt.history if m.role == ChatRole.ASSISTANT and m.tool_calls)
    assert [c["id"] for c in asst.tool_calls] == ["a"]


def test_one_shot_records_prompt_in_llm_request(tmp_path):
    """one_shot 辅助调用（标题/approver 等）的 llm.request 事件应记录发送的 prompt。"""
    tracer = EventLogTracer(EventStore(tmp_path / "sessions"))
    rt = _make_runtime(tmp_path, tracer, reply="allow")
    rt.one_shot("请判断是否允许删除 /tmp/x", "sess_o1")
    events = list(EventStore(tmp_path / "sessions").read("sess_o1"))
    req = next(e for e in events if e.type == EventType.LLM_REQUEST)
    assert req.payload.get("task") == "one_shot"
    assert req.payload.get("prompt") == "请判断是否允许删除 /tmp/x"


def test_llm_request_records_prompt(tmp_path):
    """普通对话 llm.request 事件只记录本轮输入 prompt（不含完整历史/system）。"""
    tracer = EventLogTracer(EventStore(tmp_path / "sessions"))
    rt = _make_runtime(tmp_path, tracer, reply="已完成")
    rt.run("请分析项目", "sess_p1")
    events = list(EventStore(tmp_path / "sessions").read("sess_p1"))
    req = next(e for e in events if e.type == EventType.LLM_REQUEST and e.payload.get("step") == 1)
    assert req.payload.get("prompt") == "请分析项目"
    assert "system" not in req.payload.get("prompt", "")
    # 完整工具 schema 也记录（LLM 靠它生成参数）
    schema = req.payload.get("tools_schema")
    assert isinstance(schema, list) and schema
    shell = next((s for s in schema if s["function"]["name"] == "shell"), None)
    assert shell is not None
    assert "cmd" in shell["function"]["parameters"]["properties"]


def test_system_prompt_recorded_on_first_run(tmp_path):
    """首次执行时记录当时的 system prompt 为遥测事件；后续轮次不重复。"""
    tracer = EventLogTracer(EventStore(tmp_path / "sessions"))
    rt = _make_runtime(tmp_path, tracer, reply="完成")
    rt.run("第一问", "sess_sp1")
    events = list(EventStore(tmp_path / "sessions").read("sess_sp1"))
    sp = next(e for e in events if e.type == EventType.SESSION_SYSTEM_PROMPT)
    assert sp.payload["agent"] == "main"
    assert "你是测试助手" in sp.payload["prompt"]

    # 第二轮不再重复记录（"最初的 system prompt"只记一次）
    rt.run("第二问", "sess_sp1")
    events2 = list(EventStore(tmp_path / "sessions").read("sess_sp1"))
    sps = [e for e in events2 if e.type == EventType.SESSION_SYSTEM_PROMPT]
    assert len(sps) == 1



class _SpyMock(MockProvider):
    """记录每次 stream_chat 收到的 messages，供断言图片是否注入。"""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.seen: list[list[ChatMessage]] = []

    def stream_chat(self, messages, **kw):
        self.seen.append(list(messages))
        return super().stream_chat(messages, **kw)


def test_runtime_attach_image_injects_images_next_call(tmp_path):
    """attach_image 工具把图片加入待注入队列，下一轮请求 messages 含多模态图片（且不破坏 tool_call 顺序）。"""
    tracer = EventLogTracer(EventStore(tmp_path / "sessions"))
    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfakedata")

    spy = _SpyMock(
        reply="图片分析完成",
        tool_calls=[_tool_call("attach_image", {"path": str(img)})],
    )
    agent = AgentConfig(
        id="vision",
        role=AgentRole.SUB,
        system_prompt="你是视觉代理。",
        model="mock/mock-model",
        tools=AgentToolsConfig(enabled=["attach_image"]),
    )
    rt = AgentRuntime(
        agent=BaseAgent(agent),
        router=ProviderRouter([spy]),
        tools=ToolRegistry.with_builtins(),
        permissions=PermissionChecker([], mode=ApprovalMode.AUTO),
        tracer=tracer,
        workspace=tmp_path,
        max_steps=5,
    )
    rt.run("查看图片", "sess_v1")

    assert len(spy.seen) >= 2, "应至少两轮请求（工具执行前 / 执行后）"
    # 首轮（attach_image 尚未执行）：不应有图片消息
    assert not [m for m in spy.seen[0] if m.images]
    # 第二轮：注入的多模态图片消息位于 messages 末尾（在 TOOL 结果之后）
    with_img = [m for m in spy.seen[1] if m.images]
    assert with_img and with_img[0].images == [str(img)]
    assert spy.seen[1][-1] is with_img[0], "图片消息应为本轮最后一条"

