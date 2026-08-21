"""P0：遥测事件信封与 taxonomy 单测。"""

import json

from mira.telemetry.events import Event, EventType


def test_taxonomy_expected_types():
    expected = {
        "session.created",
        "session.closed",
        "session.status",
        "session.titled",
        "user.message",
        "agent.message",
        "agent.message.delta",
        "llm.request",
        "llm.stream_chunk",
        "llm.response",
        "tool.call",
        "tool.result",
        "tool.error",
        "agent.loop.start",
        "agent.loop.end",
        "agent.spawn",
        "agent.join",
        "agent.report",
        "task.dispatch",
        "task.start",
        "task.complete",
        "task.failed",
        "skill.used",
        "approval.requested",
        "approval.resolved",
        "error.raised",
        "metric.snapshot",
    }
    assert {t.value for t in EventType} == expected


def test_event_defaults():
    ev = Event(type=EventType.LLM_REQUEST, session_id="sess_1", span_id="sp_1")
    assert ev.event_id
    assert ev.ts.endswith("Z") or "T" in ev.ts
    assert ev.parent_span_id is None
    assert ev.seq == 0


def test_event_span_context():
    ev = Event(
        type=EventType.TOOL_CALL,
        session_id="sess_1",
        span_id="sp_2",
        parent_span_id="sp_1",
        payload={"name": "shell"},
    )
    assert ev.parent_span_id == "sp_1"
    assert ev.payload["name"] == "shell"


def test_event_json_roundtrip():
    ev = Event(type=EventType.AGENT_MESSAGE, session_id="s", payload={"content": "hi"})
    raw = ev.model_dump_json()
    parsed = json.loads(raw)
    assert parsed["type"] == "agent.message"
    assert parsed["payload"]["content"] == "hi"
    ev2 = Event.model_validate_json(raw)
    assert ev2.event_id == ev.event_id
    assert ev2.type == EventType.AGENT_MESSAGE
