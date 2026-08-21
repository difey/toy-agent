"""P0 验收测试：mock provider 跑一次无工具 LLM 调用 → JSONL 事件文件（含 span 上下文）。"""

from pathlib import Path

from mira.core.config.store import ConfigStore
from mira.core.providers.base import ChatMessage, ChatRole
from mira.core.providers.router import ProviderRouter
from mira.telemetry.events import EventType
from mira.telemetry.store import EventStore
from mira.telemetry.tracer import EventLogTracer


def _run_once(sessions_dir: Path) -> list:
    store = ConfigStore()
    router = ProviderRouter.from_configs(store.providers())
    tracer = EventLogTracer(EventStore(sessions_dir))

    session_id = "sess_p0_acceptance"
    root_span, llm_span = "sp_1", "sp_2"

    tracer.emit(
        EventType.SESSION_CREATED,
        {"agent": "main"},
        session_id=session_id,
        span_id=root_span,
    )
    messages = [
        ChatMessage(role=ChatRole.SYSTEM, content="你是骨架演示。"),
        ChatMessage(role=ChatRole.USER, content="你好。"),
    ]
    tracer.emit(
        EventType.LLM_REQUEST,
        {"provider": "mock", "model": "mock-model"},
        session_id=session_id,
        span_id=llm_span,
        parent_span_id=root_span,
    )
    usage = None
    for chunk in router.stream_chat(
        "mock", messages, model="mock-model", max_retries=0
    ):
        if chunk.text:
            tracer.emit(
                EventType.LLM_STREAM_CHUNK,
                {"text": chunk.text},
                session_id=session_id,
                span_id=llm_span,
                parent_span_id=root_span,
            )
        if chunk.usage:
            usage = chunk.usage
    tracer.emit(
        EventType.LLM_RESPONSE,
        {"usage": usage.model_dump() if usage else {}},
        session_id=session_id,
        span_id=llm_span,
        parent_span_id=root_span,
    )
    tracer.emit(
        EventType.SESSION_STATUS,
        {"status": "idle"},
        session_id=session_id,
        span_id=root_span,
    )
    return list(EventStore(sessions_dir).read(session_id))


def test_p0_acceptance_produces_jsonl_with_span_context(tmp_path: Path):
    events = _run_once(tmp_path / "sessions")

    # 事件文件存在且包含若干事件
    assert len(events) >= 5  # session.created + llm.request + chunk*(≥1) + llm.response + session.status

    # 信封字段完整
    for ev in events:
        assert ev.event_id
        assert ev.ts
        assert ev.session_id == "sess_p0_acceptance"
        assert ev.seq >= 1

    # seq 严格递增（有序事件流）
    seqs = [ev.seq for ev in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)

    # span 树：会话事件挂在根 span，LLM 事件挂在子 span 且 parent 指向根 span
    for ev in events:
        if ev.type in (EventType.SESSION_CREATED, EventType.SESSION_STATUS):
            assert ev.span_id == "sp_1"
        if ev.type in (
            EventType.LLM_REQUEST,
            EventType.LLM_STREAM_CHUNK,
            EventType.LLM_RESPONSE,
        ):
            assert ev.span_id == "sp_2"
            assert ev.parent_span_id == "sp_1"

    # llm.response 携带 usage（成本/用量来自 mock 响应，决策 #6）
    resp = next(ev for ev in events if ev.type == EventType.LLM_RESPONSE)
    assert resp.payload["usage"]["total_tokens"] > 0

    # 事件文件真实落盘（sessions/<session_id>/session_id.jsonl）
    path = (
        tmp_path / "sessions" / "sess_p0_acceptance" / "session_id.jsonl"
    )
    assert path.exists()
    assert path.read_text(encoding="utf-8").strip()
