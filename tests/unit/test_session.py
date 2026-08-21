"""P1：应用层（AppClient / SessionManager / EventStream）单测。"""

from pathlib import Path

from mira import paths
from mira.api.client import AppClient
from mira.api.stream import EventStream
from mira.telemetry.events import Event, EventType


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
