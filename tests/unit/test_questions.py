"""提问通道（QuestionGate）单测：发起 / 阻塞等待 / 作答 / 中断 / 挂起列表 / 状态回调。"""

import threading
import time

import pytest

from mira.api.questions import QuestionGate, QuestionStatus


def test_request_returns_pending():
    gate = QuestionGate("s1")
    q = gate.request("要 A 还是 B？", ["A", "B"])
    assert q.status == QuestionStatus.PENDING
    assert q.question == "要 A 还是 B？"
    assert q.options == ["A", "B"]
    assert [x.id for x in gate.pending()] == [q.id]


def test_wait_blocks_then_answer_resumes():
    gate = QuestionGate("s1")
    q = gate.request("确认继续？", ["是", "否"])
    result: dict = {}

    def worker():
        result["resolved"] = gate.wait(q)

    th = threading.Thread(target=worker)
    th.start()
    time.sleep(0.05)
    assert th.is_alive()  # 未作答前阻塞
    gate.answer(q.id, "是")
    th.join(timeout=2)
    assert not th.is_alive()
    assert result["resolved"].answer == "是"
    assert result["resolved"].status == QuestionStatus.ANSWERED
    assert gate.pending() == []


def test_answer_unknown_raises():
    gate = QuestionGate("s1")
    with pytest.raises(KeyError):
        gate.answer("nope", "x")


def test_interrupt_unblocks_with_placeholder():
    gate = QuestionGate("s1")
    q = gate.request("需要确认")
    result: dict = {}

    def worker():
        result["resolved"] = gate.wait(q)

    th = threading.Thread(target=worker)
    th.start()
    time.sleep(0.05)
    gate.interrupt()
    th.join(timeout=2)
    assert not th.is_alive()
    assert result["resolved"].status == QuestionStatus.ANSWERED
    assert "未回答" in result["resolved"].answer


def test_multiple_pending_and_partial_answer():
    gate = QuestionGate("s1")
    q1 = gate.request("问题一")
    q2 = gate.request("问题二")
    assert len(gate.pending()) == 2
    gate.answer(q1.id, "答案一")
    assert [q.id for q in gate.pending()] == [q2.id]


def test_on_state_change_notified():
    states: list[bool] = []
    gate = QuestionGate("s1", on_state_change=lambda sid, w: states.append(w))
    q = gate.request("问题")
    assert states == [True]
    gate.answer(q.id, "答")
    assert states == [True, False]
