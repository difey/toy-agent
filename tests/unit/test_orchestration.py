"""P3：TaskDispatcher 编排单测（分派 / 汇报 / 报告落盘 / span 树 / 上下文隔离）。"""

import json
from pathlib import Path

from mira.api.approval import ApprovalGate
from mira.api.protocol import ReportStatus, TaskSpec
from mira.core.agents.base import BaseAgent
from mira.core.agents.registry import AgentRegistry
from mira.core.config.schemas import (
    AgentConfig,
    AgentRole,
    AgentToolsConfig,
    ApprovalMode,
)
from mira.core.config.store import ConfigStore
from mira.core.orchestration import TaskDispatcher
from mira.core.providers.mock import MockProvider
from mira.core.providers.router import ProviderRouter
from mira.core.runtime import AgentRuntime
from mira.core.tools.base import ToolContext
from mira.core.tools.builtin.dispatch import DispatchTaskTool
from mira.core.tools.permission import PermissionChecker
from mira.core.tools.registry import ToolRegistry
from mira.telemetry.events import EventType
from mira.telemetry.store import EventStore
from mira.telemetry.tracer import EventLogTracer


def _agents() -> AgentRegistry:
    return AgentRegistry(
        {
            "main": AgentConfig(
                id="main",
                role=AgentRole.MAIN,
                system_prompt="主",
                model="mock/m",
                tools=AgentToolsConfig(enabled=["dispatch_task", "file_read"]),
            ),
            "investigator": AgentConfig(
                id="investigator",
                role=AgentRole.SUB,
                system_prompt="调查",
                model="mock/m",
                tools=AgentToolsConfig(enabled=["file_read"]),
            ),
        }
    )


def _dispatcher(tmp_path, tracer, *, sub_reply="调查结论：模块划分合理", approvals=None):
    agents = _agents()
    router = ProviderRouter([MockProvider(id="mock", reply=sub_reply)])
    return TaskDispatcher(
        store=ConfigStore(),
        agents=agents,
        router=router,
        skills=None,
        tracer=tracer,
        workspace=tmp_path,
        approvals=approvals,
    )


def test_dispatcher_runs_sub_agent_and_persists_report(tmp_path):
    tracer = EventLogTracer(EventStore(tmp_path / "sessions"))
    disp = _dispatcher(tmp_path, tracer)
    spec = TaskSpec(target_agent="investigator", goal="调查模块划分", instructions="只读")

    report = disp.dispatch(spec, "s1", parent_span_id="sp_root")

    assert report.status == ReportStatus.SUCCEEDED
    assert "调查结论" in report.summary
    assert report.report_path
    assert Path(report.report_path).exists()
    text = Path(report.report_path).read_text(encoding="utf-8")
    assert "调查结论" in text and spec.task_id in text

    # 事件 span 树：main → task.dispatch → agent.spawn → agent.loop.* → agent.join
    events = list(EventStore(tmp_path / "sessions").read("s1"))
    types = [e.type for e in events]
    for t in (
        EventType.TASK_DISPATCH,
        EventType.AGENT_SPAWN,
        EventType.TASK_START,
        EventType.AGENT_LOOP_START,
        EventType.AGENT_LOOP_END,
        EventType.AGENT_JOIN,
        EventType.TASK_COMPLETE,
        EventType.AGENT_REPORT,
    ):
        assert t in types, f"缺少事件 {t}"

    dispatch = next(e for e in events if e.type == EventType.TASK_DISPATCH)
    spawn = next(e for e in events if e.type == EventType.AGENT_SPAWN)
    loop_start = next(e for e in events if e.type == EventType.AGENT_LOOP_START)
    join = next(e for e in events if e.type == EventType.AGENT_JOIN)
    assert dispatch.parent_span_id == "sp_root"
    assert spawn.parent_span_id == dispatch.span_id
    assert loop_start.parent_span_id == spawn.span_id  # 子 agent 运行挂在 spawn 下
    assert join.parent_span_id == dispatch.span_id


def test_compose_task_prompt_includes_images():
    """分派 prompt 的文本里应包含图片路径（多模态注入失效时子 agent 也能凭路径自行查看）。"""
    spec = TaskSpec(target_agent="vision", goal="看图", images=["/tmp/a.png", "/tmp/b.jpg"])
    prompt = TaskDispatcher._compose_task_prompt(spec)
    assert "附加图片路径" in prompt
    assert "/tmp/a.png" in prompt and "/tmp/b.jpg" in prompt


def test_dispatcher_injects_images_into_sub_prompt(tmp_path):
    """dispatch 带 images 时，子 agent 的 user.message 遥测事件应含图片路径（而非只靠反思）。"""
    tracer = EventLogTracer(EventStore(tmp_path / "sessions"))
    disp = _dispatcher(tmp_path, tracer)
    spec = TaskSpec(
        target_agent="investigator",
        goal="看图",
        images=["/tmp/a.png", "/tmp/b.jpg"],
    )
    disp.dispatch(spec, "s3", parent_span_id="sp_root")
    events = list(EventStore(tmp_path / "sessions").read("s3"))
    sub_user = next(
        e for e in events
        if e.type == EventType.USER_MESSAGE and "附加图片路径" in (e.payload.get("content") or "")
    )
    assert "/tmp/a.png" in sub_user.payload["content"]
    assert "/tmp/b.jpg" in sub_user.payload["content"]


def test_dispatch_task_tool_drives_sub_agent_without_polluting_main(tmp_path):
    tracer = EventLogTracer(EventStore(tmp_path / "sessions"))
    agents = _agents()
    # 子 agent 用普通 router（无工具调用）；主 agent 用带 dispatch_task 调用的 router
    sub_router = ProviderRouter([MockProvider(id="mock", reply="子调查结果")])
    disp = TaskDispatcher(
        store=ConfigStore(),
        agents=agents,
        router=sub_router,
        skills=None,
        tracer=tracer,
        workspace=tmp_path,
    )
    call = {
        "id": "c1",
        "type": "function",
        "function": {
            "name": "dispatch_task",
            "arguments": json.dumps(
                {"target_agent": "investigator", "goal": "调查 X", "context": ["docs/a.md"]}
            ),
        },
    }
    main_router = ProviderRouter(
        [MockProvider(id="mock", reply="已汇总", tool_calls=[call])]
    )
    tools = ToolRegistry.with_builtins()
    tools.register(DispatchTaskTool())
    main = BaseAgent(agents.get("main").config)
    rt = AgentRuntime(
        agent=main,
        router=main_router,
        tools=tools,
        permissions=PermissionChecker([], mode=ApprovalMode.AUTO),
        tracer=tracer,
        workspace=tmp_path,
        dispatcher=disp,
        tools_override=["dispatch_task", "file_read"],
    )

    reply = rt.run("请调查", "s2")
    assert "已汇总" in reply

    events = list(EventStore(tmp_path / "sessions").read("s2"))
    assert any(e.type == EventType.TASK_COMPLETE for e in events)
    # dispatch_task 工具结果含摘要 + 报告路径
    result_ev = next(
        e for e in events if e.type == EventType.TOOL_RESULT and "子任务" in (e.payload.get("result") or "")
    )
    assert "子调查结果" in result_ev.payload["result"]
    assert "reports/" in result_ev.payload["result"]

    # 子 agent 上下文隔离：主 agent 历史不含子 agent 的任务提示
    user_msgs = [m for m in rt.history if m.role.value == "user"]
    assert len(user_msgs) == 1
    assert "任务目标" not in user_msgs[0].content


def test_dispatcher_unknown_agent_raises(tmp_path):
    tracer = EventLogTracer(EventStore(tmp_path / "sessions"))
    disp = _dispatcher(tmp_path, tracer)
    import pytest

    with pytest.raises(ValueError):
        disp.dispatch(TaskSpec(target_agent="nope", goal="x"), "s1", "sp_root")


def test_dispatch_tool_requires_dispatcher():
    tool = DispatchTaskTool()
    result = tool.run(ToolContext(workspace=".", session_id="s1", meta={}), target_agent="investigator", goal="g")
    assert not result.ok
    assert "dispatcher" in (result.error or "")


def test_dispatch_tool_dynamic_targets_from_config():
    """可选目标动态来自 registry：工具描述/schema 反映可用子 agent，未知目标被拒绝。"""
    tool = DispatchTaskTool(
        available=[
            {"id": "investigator", "name": "实现调查员", "description": "调查实现状态"},
            {"id": "vision", "name": "视觉代理", "description": "查看图片"},
        ]
    )
    assert "investigator" in tool.description and "vision" in tool.description
    target_desc = tool.params_schema["properties"]["target_agent"]["description"]
    assert "investigator" in target_desc and "vision" in target_desc
    # 不在可用列表的目标被拒绝，错误提示可用目标
    res = tool.run(
        ToolContext(workspace=".", session_id="s1", meta={"dispatcher": object()}),
        target_agent="nope",
        goal="g",
    )
    assert not res.ok
    assert "investigator" in (res.error or "")


def test_session_manager_end_to_end_dispatch(tmp_path):
    """走真实 SessionManager 接线：主 agent（dispatch=auto）经 dispatch_task 分派子 agent。"""
    from mira.api.client import AppClient
    from mira.api.session import SessionManager

    call = {
        "id": "c1",
        "type": "function",
        "function": {
            "name": "dispatch_task",
            "arguments": json.dumps(
                {"target_agent": "investigator", "goal": "调查模块划分"}
            ),
        },
    }
    router = ProviderRouter(
        [MockProvider(id="mock", reply="已汇总", tool_calls=[call], tool_calls_once=True)]
    )
    client = AppClient(SessionManager(router=router))
    sess = client.create_session(tmp_path, agent_type="main")
    client.send_message(sess.id, "请调查一下模块划分", model=sess.model)

    events = []
    for ev in client.events(sess.id):
        events.append(ev)
        if ev.type == EventType.SESSION_STATUS and ev.payload.get("status") in ("idle", "failed"):
            break

    types = [e.type for e in events]
    assert EventType.TASK_DISPATCH in types
    assert EventType.AGENT_SPAWN in types
    assert EventType.TASK_COMPLETE in types
    assert EventType.AGENT_REPORT in types
    assert client.get_session(sess.id).status.value == "idle"

    # 报告落盘（决策 #7 / #23）
    report_ev = next(e for e in events if e.type == EventType.AGENT_REPORT)
    p = Path(report_ev.payload["report_path"])
    assert p.exists()
    assert "已汇总" in p.read_text(encoding="utf-8")
    assert "reports/" in str(p) and p.name.endswith(".md") and p.name != ".md"


def test_sub_agent_model_effort_inheritance(tmp_path):
    """决策 #25：子 agent 的 model/effort 可选——未配置则继承父 runtime 本轮值；配置了则用自己的。"""
    tracer = EventLogTracer(EventStore(tmp_path / "sessions"))
    agents = AgentRegistry(
        {
            "no-model-sub": AgentConfig(
                id="no-model-sub", role=AgentRole.SUB, system_prompt="子A",
                tools=AgentToolsConfig(enabled=["file_read"]),
            ),
            "own-model-sub": AgentConfig(
                id="own-model-sub", role=AgentRole.SUB, system_prompt="子B",
                model="mock/own-model", effort="low", tools=AgentToolsConfig(enabled=["file_read"]),
            ),
        }
    )
    router = ProviderRouter([MockProvider(id="mock", reply="子回复")])
    disp = TaskDispatcher(
        store=ConfigStore(),
        agents=agents,
        router=router,
        skills=None,
        tracer=tracer,
        workspace=tmp_path,
    )

    def sub_request(sid: str, target: str, parent_model: str | None, parent_effort: str | None) -> dict:
        disp.dispatch(
            TaskSpec(target_agent=target, goal="g"), sid, "sp_root",
            model=parent_model, effort=parent_effort,
        )
        events = list(EventStore(tmp_path / "sessions").read(sid))
        req = next(e for e in events if e.type == EventType.LLM_REQUEST)
        return req.payload

    # 1) 未配置 → 继承父 runtime 本轮 model/effort（LLM_REQUEST 记录拆分后的模型名 + provider）
    p1 = sub_request("s1", "no-model-sub", "mock/parent-model", "high")
    assert p1["model"] == "parent-model"
    assert p1["provider"] == "mock"
    assert p1["effort"] == "high"

    # 2) 配置了 model/effort → 用自己的
    p2 = sub_request("s2", "own-model-sub", "mock/parent-model", "high")
    assert p2["model"] == "own-model"
    assert p2["provider"] == "mock"
    assert p2["effort"] == "low"
