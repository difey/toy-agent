"""Pending user interaction state (permission requests, questions) and its public view."""

import asyncio


class InteractionState:
    """Encapsulates pending user interaction state and its public view."""

    def __init__(self):
        self._pending_permission: dict | None = None
        self._pending_question: dict | None = None
        self._next_request_id = 1

    def _request_id(self) -> str:
        request_id = f"req_{self._next_request_id}"
        self._next_request_id += 1
        return request_id

    def begin_permission(
        self,
        future: asyncio.Future,
        *,
        tool: str,
        target: str,
        resolved_path: str,
        cwd: str,
    ) -> dict:
        self._pending_permission = {
            "future": future,
            "request_id": self._request_id(),
            "tool": tool,
            "target": target,
            "resolved_path": resolved_path,
            "cwd": cwd,
        }
        return self._pending_permission

    def clear_permission(self) -> None:
        self._pending_permission = None

    def respond_permission(self, decision: str) -> None:
        """Validate and resolve a pending permission request.
        
        Raises RuntimeError if no request is pending.
        """
        if self._pending_permission is None:
            raise RuntimeError("No pending permission request")
        if decision not in ("allow", "deny", "allow_always"):
            raise ValueError("Decision must be 'allow', 'deny', or 'allow_always'")
        future = self._pending_permission["future"]
        if not future.done():
            future.set_result(decision)

    def begin_question(
        self,
        future: asyncio.Future,
        *,
        header: str,
        question: str,
        options: list[dict],
        multiple: bool,
    ) -> dict:
        self._pending_question = {
            "future": future,
            "request_id": self._request_id(),
            "header": header,
            "question": question,
            "options": options,
            "multiple": multiple,
        }
        return self._pending_question

    def clear_question(self) -> None:
        self._pending_question = None

    def respond_question(self, answer: str | list[str]) -> None:
        """Validate and resolve a pending question.
        
        Raises RuntimeError if no question is pending.
        """
        if self._pending_question is None:
            raise RuntimeError("No pending question")
        if isinstance(answer, str):
            answer = [answer]
        future = self._pending_question["future"]
        if not future.done():
            future.set_result(answer)

    @property
    def pending_permission(self) -> dict | None:
        return self._pending_permission

    @property
    def pending_question(self) -> dict | None:
        return self._pending_question

    def view(self) -> dict:
        permission_view = None
        question_view = None
        if self._pending_permission is not None:
            permission_view = {
                "request_id": self._pending_permission["request_id"],
                "tool": self._pending_permission["tool"],
                "target": self._pending_permission["target"],
                "resolved_path": self._pending_permission["resolved_path"],
                "cwd": self._pending_permission["cwd"],
            }
        if self._pending_question is not None:
            question_view = {
                "request_id": self._pending_question["request_id"],
                "header": self._pending_question["header"],
                "question": self._pending_question["question"],
                "options": self._pending_question["options"],
                "multiple": self._pending_question["multiple"],
            }
        return {
            "pending_permission": permission_view,
            "pending_question": question_view,
        }
