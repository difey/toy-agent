"""EventStream：核心层产出的结构化事件流（订阅 / 缓冲 / 快照 / 断线补偿）。

CLI 与 Web 均通过它消费事件；事件按 session 内 seq 有序（seq 由 Tracer 分配）。
"""

from __future__ import annotations

import threading
from collections.abc import Iterator

from mira.telemetry.events import Event
from mira.telemetry.tracer import BaseTracer


class EventStream:
    """线程安全的事件流：缓冲 + 阻塞迭代 + 快照。"""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._buffer: list[Event] = []
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._closed = False

    def append(self, event: Event) -> None:
        with self._cond:
            self._buffer.append(event)
            self._cond.notify_all()

    def iter_events(self, start_seq: int = 0) -> Iterator[Event]:
        """按 seq 有序迭代：先补发缓冲，再实时等待新事件，直到 close()。"""
        with self._cond:
            i = 0
            while i < len(self._buffer) and self._buffer[i].seq < start_seq:
                i += 1
        while True:
            with self._cond:
                while i >= len(self._buffer) and not self._closed:
                    self._cond.wait()
                if i >= len(self._buffer):
                    return
                event = self._buffer[i]
                i += 1
            yield event

    def snapshot(self, last_n: int | None = None) -> list[Event]:
        with self._lock:
            events = list(self._buffer)
        if last_n is not None:
            return events[-last_n:]
        return events

    def last_seq(self) -> int:
        with self._lock:
            return self._buffer[-1].seq if self._buffer else 0

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify_all()


class StreamTracer(BaseTracer):
    """将事件转发到 EventStream（实时订阅；seq 由 CompositeTracer 统一分配）。"""

    def __init__(self, stream: EventStream) -> None:
        super().__init__()
        self.stream = stream

    def record(self, event: Event) -> None:
        self.stream.append(event)
