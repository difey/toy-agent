"""提问（HITL）：/sessions/{id}/questions。

agent 经 ask_question 工具挂起问题（question.requested 事件流出），
用户点选选项或自由输入回答后 POST 本端点，答案作为工具结果回填给 LLM。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from mira.web.router.models import AnswerQuestionBody

router = APIRouter(prefix="/api")


@router.get("/sessions/{session_id}/questions")
def pending_questions(session_id: str, request: Request) -> list[dict]:
    return request.app.state.client.pending_questions(session_id)


@router.post("/sessions/{session_id}/questions/{question_id}")
def answer_question(
    session_id: str, question_id: str, body: AnswerQuestionBody, request: Request
) -> dict:
    try:
        return request.app.state.client.answer_question(
            session_id, question_id, body.answer
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
