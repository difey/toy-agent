"""P2：全局并发配额单测。"""

import threading
import time

from mira.api.quota import SessionQuota


def test_quota_acquire_release():
    q = SessionQuota(2)
    assert q.can_acquire()
    assert q.acquire() is True
    assert q.acquire() is True
    assert not q.can_acquire()
    assert q.usage()["active"] == 2
    q.release()
    assert q.can_acquire()


def test_quota_acquire_blocks_then_timeout():
    q = SessionQuota(1)
    assert q.acquire() is True
    result: dict = {}

    def try_acquire():
        result["ok"] = q.acquire(timeout=0.3)

    th = threading.Thread(target=try_acquire)
    th.start()
    th.join(timeout=2)
    assert result["ok"] is False  # 超时返回 False
    assert q.usage()["queue"] == 0

    q.release()
    assert q.acquire(timeout=0.5) is True
    q.release()


def test_quota_release_unblocks():
    q = SessionQuota(1)
    q.acquire()
    acquired = []

    def try_acquire():
        if q.acquire(timeout=2):
            acquired.append(True)
            q.release()

    th = threading.Thread(target=try_acquire)
    th.start()
    time.sleep(0.05)
    q.release()  # 释放 → 排队者拿到槽位
    th.join(timeout=3)
    assert acquired == [True]


def test_quota_nonblocking_reject():
    q = SessionQuota(1)
    q.acquire()
    assert q.acquire(timeout=0) is False
    q.release()
