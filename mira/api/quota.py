"""SessionQuota：全局并发配额 / 排队（决策 #4）。

控制同时运行的会话（turn）数；超限时阻塞排队（queue_on_quota）或直接拒绝。
"""

from __future__ import annotations

import threading
import time


class SessionQuota:
    def __init__(self, max_concurrent: int) -> None:
        self.max_concurrent = max(1, max_concurrent)
        self._cond = threading.Condition()
        self._active = 0
        self._queue = 0

    def can_acquire(self) -> bool:
        with self._cond:
            return self._active < self.max_concurrent

    def acquire(self, timeout: float | None = None) -> bool:
        """占用一个并发槽位；无空位时阻塞等待（排队）。超时返回 False。"""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            self._queue += 1
            try:
                while self._active >= self.max_concurrent:
                    if deadline is not None and time.monotonic() >= deadline:
                        return False
                    self._cond.wait(timeout=0.2)
                self._active += 1
                return True
            finally:
                self._queue -= 1

    def release(self) -> None:
        with self._cond:
            self._active = max(0, self._active - 1)
            self._cond.notify_all()

    def usage(self) -> dict:
        with self._cond:
            return {
                "active": self._active,
                "max": self.max_concurrent,
                "queue": self._queue,
            }
