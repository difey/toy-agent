"""P0：遥测骨架单测（Tracer / JSONL 存储 / 回读）。"""

from pathlib import Path

from mira.telemetry.events import EventType
from mira.telemetry.store import EventStore
from mira.telemetry.tracer import (
    CompositeTracer,
    EventLogTracer,
    NullTracer,
)


def _make_tracer(tmp_path: Path):
    store = EventStore(tmp_path / "sessions")
    tracer = EventLogTracer(store)
    return store, tracer


def test_tracer_emit_writes_jsonl(tmp_path: Path):
    store, tracer = _make_tracer(tmp_path)
    tracer.emit(
        EventType.SESSION_CREATED,
        {"session_id": "s1"},
        session_id="s1",
        span_id="sp_1",
    )
    tracer.emit(
        EventType.LLM_REQUEST,
        {},
        session_id="s1",
        span_id="sp_2",
        parent_span_id="sp_1",
    )
    path = store.path_for("s1")
    assert path.exists()
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert store.count("s1") == 2


def test_tracer_seq_increments_per_session(tmp_path: Path):
    store, tracer = _make_tracer(tmp_path)
    e1 = tracer.emit(EventType.SESSION_CREATED, {}, session_id="a")
    e2 = tracer.emit(EventType.SESSION_STATUS, {}, session_id="a")
    e3 = tracer.emit(EventType.SESSION_CREATED, {}, session_id="b")
    assert (e1.seq, e2.seq, e3.seq) == (1, 2, 1)


def test_event_span_tree_in_file(tmp_path: Path):
    store, tracer = _make_tracer(tmp_path)
    tracer.emit(
        EventType.TOOL_CALL,
        {"name": "shell"},
        session_id="s",
        span_id="sp_2",
        parent_span_id="sp_1",
    )
    events = list(store.read("s"))
    assert len(events) == 1
    ev = events[0]
    assert ev.span_id == "sp_2"
    assert ev.parent_span_id == "sp_1"
    assert ev.event_id
    assert ev.ts


def test_store_list_sessions(tmp_path: Path):
    store, tracer = _make_tracer(tmp_path)
    tracer.emit(EventType.SESSION_CREATED, {}, session_id="a")
    tracer.emit(EventType.SESSION_CREATED, {}, session_id="b")
    assert store.list_sessions() == ["a", "b"]


def test_null_tracer_drops(tmp_path: Path):
    store = EventStore(tmp_path / "sessions")
    tracer = NullTracer()
    tracer.emit(EventType.SESSION_CREATED, {}, session_id="x")
    assert not store.path_for("x").exists()


def test_composite_tracer_fans_out(tmp_path: Path):
    store1 = EventStore(tmp_path / "t1")
    store2 = EventStore(tmp_path / "t2")
    tracer = CompositeTracer(EventLogTracer(store1), EventLogTracer(store2))
    tracer.emit(EventType.SESSION_CREATED, {}, session_id="s")
    assert store1.count("s") == 1
    assert store2.count("s") == 1
