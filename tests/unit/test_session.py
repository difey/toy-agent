"""P1：应用层（AppClient / SessionManager / EventStream）单测。"""

from pathlib import Path

from mira import paths
from mira.api.approval import ApprovalDecision
from mira.api.client import AppClient
from mira.api.session import SessionManager, parse_approver_decision
from mira.api.stream import EventStream
from mira.core.config.store import global_config_dir
from mira.core.providers.mock import MockProvider
from mira.core.providers.router import ProviderRouter
from mira.telemetry.events import Event, EventType


def test_parse_approver_decision():
    """自动审批决策输出解析：allow/deny 生效；fallback/空/无法解析 → None（回退人工）。"""
    assert parse_approver_decision("allow") == ApprovalDecision.ALLOW
    assert parse_approver_decision("deny") == ApprovalDecision.DENY
    assert parse_approver_decision("fallback") is None
    assert parse_approver_decision("allow 该操作安全") == ApprovalDecision.ALLOW
    assert parse_approver_decision(" Deny! ") == ApprovalDecision.DENY
    assert parse_approver_decision("") is None
    assert parse_approver_decision("信息不足，需要人工") is None


def test_build_auto_approver_ask_mode_returns_none(tmp_path: Path):
    """默认 ask 模式不启用自动审批决策器（走原有人工审批）。"""
    sm = SessionManager()
    sess = sm.create_session(tmp_path, agent_type="main")
    assert sm._build_auto_approver(sess) is None


def test_build_auto_approver_auto_mode(tmp_path: Path):
    """auto 模式：approver agent 决策器接线，mock 输出 allow → 放行。"""
    d = global_config_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "mira.toml").write_text(
        "[approval]\nmode = 'auto'\n[session]\ndefault_agent = 'main'\n",
        encoding="utf-8",
    )
    sm = SessionManager()
    sm._router = ProviderRouter([MockProvider(id="mock", reply="allow")])
    sess = sm.create_session(tmp_path, agent_type="main")
    decide = sm._build_auto_approver(sess)
    assert decide is not None
    assert decide("file_write", {"path": "/tmp/x", "content": "y"}, None) == ApprovalDecision.ALLOW


def test_build_auto_approver_auto_mode_deny_and_fallback(tmp_path: Path):
    """auto 模式：mock 输出 deny → 拒绝；输出 fallback → 回退人工（None）。"""
    d = global_config_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "mira.toml").write_text(
        "[approval]\nmode = 'auto'\n[session]\ndefault_agent = 'main'\n",
        encoding="utf-8",
    )
    sm = SessionManager()
    sess = sm.create_session(tmp_path, agent_type="main")
    sm._router = ProviderRouter([MockProvider(id="mock", reply="deny")])
    decide = sm._build_auto_approver(sess)
    assert decide("file_write", {"path": "/tmp/x"}, None) == ApprovalDecision.DENY

    sm._router = ProviderRouter([MockProvider(id="mock", reply="fallback")])
    decide2 = sm._build_auto_approver(sess)
    assert decide2("file_write", {"path": "/tmp/x"}, None) is None


def test_auto_approval_fallback_blocks_then_resolves(tmp_path: Path):
    """auto 模式端到端：approver 无法判断(fallback) → 回退人工审批，阻塞到 resolve 后工具执行。"""
    import json as _json
    import threading
    import time

    tool_call = {
        "id": "c1",
        "type": "function",
        "function": {
            "name": "shell",
            "arguments": _json.dumps({"cmd": "echo hello"}),
        },
    }
    d = global_config_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "mira.toml").write_text(
        "[approval]\nmode = 'auto'\n[session]\ndefault_agent = 'main'\n",
        encoding="utf-8",
    )
    sm = SessionManager()
    # 主 agent 与 approver 共用 mock：主 agent 触发 file_write 工具，approver 输出 fallback（无法判断）
    sm._router = ProviderRouter(
        [MockProvider(id="mock", reply="fallback", tool_calls=[tool_call])]
    )
    sess = sm.create_session(tmp_path, agent_type="main")
    sm.send_message(sess.id, "写文件", model=sess.model)
    for _ in range(100):
        if sm.pending_approvals(sess.id):
            break
        time.sleep(0.02)
    reqs = sm.pending_approvals(sess.id)
    assert reqs, "approver 无法判断应回退到人工审批"
    sm.resolve_approval(sess.id, reqs[0]["id"], "allow")
    for _ in range(200):
        if sm.get(sess.id).status.value in ("idle", "failed"):
            break
        time.sleep(0.02)
    assert sm.get(sess.id).status.value == "idle"


def test_client_session_flow(tmp_path: Path):
    client = AppClient()  # 默认 router 来自配置（mock）
    sess = client.create_session(tmp_path, agent_type="main")
    assert sess.id
    assert sess.workspace == str(tmp_path)
    assert sess.model.startswith("mock/")  # 模型串 {provider}/{model}（决策 #26：provider 由模型推导）

    client.send_message(sess.id, "你好", model=sess.model)
    events = []
    for ev in client.events(sess.id):
        events.append(ev)
        if ev.type == EventType.SESSION_STATUS and ev.payload.get("status") in ("idle", "failed"):
            break

    types = [e.type for e in events]
    assert EventType.SESSION_CREATED in types
    assert EventType.USER_MESSAGE in types
    assert EventType.LLM_REQUEST in types
    assert EventType.LLM_STREAM_CHUNK in types
    assert EventType.LLM_RESPONSE in types
    assert EventType.AGENT_LOOP_END in types
    assert EventType.SESSION_STATUS in types

    assert client.get_session(sess.id).status.value == "idle"

    # JSONL 落盘：sessions/<session_id>/session_id.jsonl
    log_path = paths.session_log_path(sess.workspace, sess.id)
    assert log_path.exists()

    # 会话列表
    assert any(s.id == sess.id for s in client.list_sessions())


def test_unknown_session_raises():
    client = AppClient()
    import pytest

    with pytest.raises(KeyError):
        list(client.events("nope"))


def test_historical_session_is_loaded_when_sending(tmp_path: Path):
    first = AppClient()
    original = first.create_session(tmp_path, agent_type="main")
    first.send_message(original.id, "第一轮", model=original.model)
    for event in first.events(original.id):
        if event.type == EventType.SESSION_STATUS and event.payload.get("status") == "idle":
            break

    restarted = AppClient()
    thread = restarted.send_message(original.id, "第二轮", model=original.model)
    assert thread is not None
    restored = restarted.get_session(original.id)
    assert restored.workspace == str(tmp_path)
    assert restored.agent_type == original.agent_type
    assert restored.model == original.model

    thread.join(timeout=10)
    assert not thread.is_alive()
    events = restarted.manager.events(original.id).snapshot()
    assert any(
        event.type == EventType.USER_MESSAGE and event.payload.get("content") == "第二轮"
        for event in events
    )


def test_unknown_agent_raises(tmp_path):
    client = AppClient()
    import pytest

    with pytest.raises(ValueError):
        client.create_session(tmp_path, agent_type="no-such-agent")


def test_event_stream_buffer_and_seq():
    stream = EventStream("s1")
    stream.append(Event(type=EventType.SESSION_CREATED, session_id="s1", seq=1))
    stream.append(Event(type=EventType.SESSION_STATUS, session_id="s1", seq=2))
    stream.close()
    events = list(stream.iter_events())
    assert [e.seq for e in events] == [1, 2]
    assert stream.last_seq() == 2
    assert len(stream.snapshot()) == 2
    assert len(stream.snapshot(last_n=1)) == 1
