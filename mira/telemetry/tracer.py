"""Tracer 接口与实现：核心层通过注入式 Tracer 采集遥测（对核心逻辑零侵入）。

每个事件带 span 上下文（span_id / parent_span_id），一次 agent 运行 = 一棵事件树。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict

from mira.telemetry.events import Event, EventType
from mira.telemetry.store import EventStore


class BaseTracer(ABC):
    """Tracer 基类：负责 stamp 信封（event_id / ts / seq 按 session 递增）。"""

    def __init__(self) -> None:
        self._seqs: dict[str, int] = defaultdict(int)

    def emit(
        self,
        type_: EventType | str,
        payload: dict | None = None,
        *,
        session_id: str,
        span_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> Event:
        self._seqs[session_id] += 1
        event = Event(
            type=EventType(type_),
            payload=payload or {},
            session_id=session_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            seq=self._seqs[session_id],
        )
        self.record(event)
        return event

    @abstractmethod
    def record(self, event: Event) -> None:
        """将事件写入具体存储 / 转发给订阅者。"""


class NullTracer(BaseTracer):
    """空实现（遥测关闭时使用）。"""

    def record(self, event: Event) -> None:
        pass


class EventLogTracer(BaseTracer):
    """默认实现：事件落盘到 JSONL（EventStore）。"""

    def __init__(self, store: EventStore) -> None:
        super().__init__()
        self.store = store

    def record(self, event: Event) -> None:
        self.store.append(event)


class CompositeTracer(BaseTracer):
    """扇出到多个 Tracer（如 JSONL 落盘 + 实时订阅 + 指标聚合）。"""

    def __init__(self, *children: BaseTracer) -> None:
        super().__init__()
        self.children = children

    def record(self, event: Event) -> None:
        for child in self.children:
            child.record(event)
