"""内建工具：ask_question — agent 在需要与用户确认细节时向用户提问。

- 问题挂到运行时注入的提问通道（ToolContext.meta["question_gate"]）；
- 事件 question.requested 流出 → Web 弹窗 / CLI 提示展示问题与预设选项；
- 用户作答（点选选项或自由输入）后解除阻塞，答案作为工具结果回填给 LLM。
"""

from __future__ import annotations

from typing import Any

from mira.api.questions import QuestionStatus
from mira.core.tools.base import Tool, ToolContext, ToolResult
from mira.telemetry.events import EventType


class AskQuestionTool(Tool):
    name = "ask_question"
    description = (
        "向用户提出一个需要确认的问题（如需求细节、实现取舍、选项偏好），"
        "用户回答后工具返回其回答。仅在信息不足、需要用户拍板时使用，避免频繁打断。"
    )
    params_schema = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "需要用户确认的问题（简明、一次只问一个）",
            },
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "建议的可选答案（用户可直接点选，也可自由输入回答）",
            },
        },
        "required": ["question"],
    }

    def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
        gate = (ctx.meta or {}).get("question_gate")
        if gate is None:
            return ToolResult(
                ok=False, error="ask_question 需要在运行时会话中执行（缺少提问通道）"
            )
        question = str(args.get("question", "")).strip()
        options = [str(o).strip() for o in (args.get("options") or []) if str(o).strip()]
        if not question:
            return ToolResult(ok=False, error="question 为必填参数")

        # 同一批多个提问时的进度（由运行时统计：2/4 等）；单问/未知时为 None
        progress = (ctx.meta or {}).get("question_progress")
        index, total = progress if isinstance(progress, tuple) and len(progress) == 2 else (None, None)
        q = gate.request(question, options, index=index, total=total)
        span = str((ctx.meta or {}).get("span_id") or "")
        tracer = (ctx.meta or {}).get("tracer")
        if tracer is not None:
            payload: dict[str, Any] = {
                "request_id": q.id,
                "question": question,
                "options": options,
            }
            if q.index is not None and q.total is not None:
                payload["index"] = q.index
                payload["total"] = q.total
            tracer.emit(
                EventType.QUESTION_REQUESTED,
                payload,
                session_id=ctx.session_id,
                span_id=span,
            )
        if q.status == QuestionStatus.PENDING:
            q = gate.wait(q)  # 阻塞直到用户作答 / 中断
        if tracer is not None:
            tracer.emit(
                EventType.QUESTION_ANSWERED,
                {"request_id": q.id, "question": question, "answer": q.answer or ""},
                session_id=ctx.session_id,
                span_id=span,
            )
        return ToolResult(
            ok=True,
            output=f"用户回答：{q.answer or '（无回答）'}",
        )
