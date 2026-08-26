"""提问通道（HITL）：agent 在需要与用户确认细节时调用 ask_question 工具。

- 工具把问题（question + 可选 options）挂到 QuestionGate，事件 question.requested 流出；
- Web 弹窗 / CLI 提示展示问题与选项，用户可点选预设选项或自由输入回答；
- 运行时 worker 线程在 wait() 上阻塞，用户作答后继续执行，
  答案作为工具结果回填给 LLM（与审批通道语义一致，决策：阻塞语义 P2）。
"""

from __future__ import annotations

import threading
from enum import Enum
from typing import Callable

from pydantic import BaseModel, Field

from mira.util import new_id, utcnow_iso


class QuestionStatus(str, Enum):
    PENDING = "pending"
    ANSWERED = "answered"


class Question(BaseModel):
    """一次提问：问题文本 + 可选预设选项；用户可点选或自由输入回答。

    index / total：同一批多个提问时的序号与总数（前端展示进度，如 2/4）。
    """

    id: str = Field(default_factory=lambda: new_id("q"))
    session_id: str
    question: str
    options: list[str] = Field(default_factory=list)
    index: int | None = None
    total: int | None = None
    answer: str | None = None
    ts: str = Field(default_factory=utcnow_iso)
    status: QuestionStatus = QuestionStatus.PENDING


class QuestionGate:
    """会话级提问通道（线程安全）。

    - request：发起提问，返回 pending 的 Question；
    - wait：阻塞直到该提问被作答（或 interrupt 打断）；
    - answer：用户作答（预设选项文本或自由输入）。
    """

    def __init__(
        self,
        session_id: str,
        on_state_change: Callable[[str, bool], None] | None = None,
    ) -> None:
        self.session_id = session_id
        self._questions: dict[str, Question] = {}
        self._cond = threading.Condition()
        self._on_state_change = on_state_change

    def request(
        self,
        question: str,
        options: list[str] | None = None,
        *,
        index: int | None = None,
        total: int | None = None,
    ) -> Question:
        """发起提问。index/total：同一批多个提问时的进度（如 2/4）。"""
        q = Question(
            session_id=self.session_id,
            question=question,
            options=list(options or []),
            index=index,
            total=total,
        )
        with self._cond:
            self._questions[q.id] = q
        self._notify_state(True)
        return q

    def wait(self, q: Question, timeout: float | None = None) -> Question:
        """阻塞直到该提问被作答；超时（默认不超时）返回当前状态。"""
        with self._cond:
            self._cond.wait_for(
                lambda: self._questions.get(q.id, q).status == QuestionStatus.ANSWERED,
                timeout=timeout,
            )
        return self._questions.get(q.id, q)

    def answer(self, question_id: str, answer: str) -> Question:
        """用户作答：写入回答并解除 wait 阻塞。"""
        with self._cond:
            q = self._questions.get(question_id)
            if q is None:
                raise KeyError(f"未知提问: {question_id!r}")
            q.status = QuestionStatus.ANSWERED
            q.answer = answer
            still_pending = self._has_pending()
            self._cond.notify_all()
        if not still_pending:
            self._notify_state(False)
        return q

    def interrupt(self) -> None:
        """中断所有待提问（视为跳过回答），使阻塞的 wait 立即返回。"""
        with self._cond:
            changed = False
            for q in self._questions.values():
                if q.status == QuestionStatus.PENDING:
                    q.status = QuestionStatus.ANSWERED
                    q.answer = "（用户中断/未回答）"
                    changed = True
            if changed:
                self._cond.notify_all()
                self._notify_state(False)

    def pending(self) -> list[Question]:
        with self._cond:
            return [q for q in self._questions.values() if q.status == QuestionStatus.PENDING]

    def _has_pending(self) -> bool:
        return any(q.status == QuestionStatus.PENDING for q in self._questions.values())

    def _notify_state(self, waiting: bool) -> None:
        if self._on_state_change:
            self._on_state_change(self.session_id, waiting)
