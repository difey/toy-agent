"""P2：审批通道（HITL）单测。"""

import threading
import time

import pytest

from mira.api.approval import ApprovalGate, ApprovalStatus


def test_approval_request_wait_resolve():
    gate = ApprovalGate("s1")
    req = gate.request("shell", {"cmd": "ls"}, None)
    assert req.status == ApprovalStatus.PENDING
    assert gate.pending()

    result: dict = {}

    def waiter():
        result["req"] = gate.wait(req)

    th = threading.Thread(target=waiter)
    th.start()
    time.sleep(0.05)
    resolved = gate.resolve(req.id, "allow")
    th.join(timeout=2)
    assert not th.is_alive()
    assert resolved.decision == "allow"
    assert result["req"].decision == "allow"
    assert not gate.pending()


def test_approval_deny():
    gate = ApprovalGate("s1")
    req = gate.request("shell", {}, None)
    gate.resolve(req.id, "deny")
    assert req.decision == "deny"
    assert not gate.pending()


def test_approval_always_override():
    gate = ApprovalGate("s1")
    req = gate.request("file_write", {"path": "a"}, "a")
    gate.resolve(req.id, "always")
    # 同 (tool, path) 自动放行
    req2 = gate.request("file_write", {"path": "a"}, "a")
    assert req2.status == ApprovalStatus.RESOLVED
    assert req2.auto is True
    # 不同 path 仍需审批
    req3 = gate.request("file_write", {"path": "b"}, "b")
    assert req3.status == ApprovalStatus.PENDING


def test_approval_unknown_request_raises():
    gate = ApprovalGate("s1")
    with pytest.raises(KeyError):
        gate.resolve("nope", "allow")


def test_approval_state_callback():
    states: list[bool] = []
    gate = ApprovalGate("s1", on_state_change=lambda sid, w: states.append(w))
    req = gate.request("shell", {}, None)
    assert states == [True]
    gate.resolve(req.id, "allow")
    assert states[-1] is False
