"""审批通道（HITL）：ask 权限命中的工具调用进入待审批状态（决策：阻塞语义 P2）。

CLI/Web 收到 approval.requested 后调用 ApprovalGate.resolve 决议（allow/deny/always），
运行时 worker 线程在 wait() 上阻塞，决议后继续执行。always 会记住 (tool, path) 后续自动放行。
"""

from __future__ import annotations

import threading
from enum import Enum
from typing import Callable

from pydantic import BaseModel, Field

from mira.util import new_id, utcnow_iso


class ApprovalDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ALWAYS = "always"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    RESOLVED = "resolved"


class ApprovalRequest(BaseModel):
    id: str = Field(default_factory=lambda: new_id("apr"))
    session_id: str
    tool: str
    arguments: dict = Field(default_factory=dict)
    path: str | None = None
    ts: str = Field(default_factory=utcnow_iso)
    status: ApprovalStatus = ApprovalStatus.PENDING
    decision: str | None = None
    auto: bool = False  # always 覆盖自动放行


class ApprovalGate:
    """会话级审批通道（线程安全）。"""

    def __init__(
        self,
        session_id: str,
        on_state_change: Callable[[str, bool], None] | None = None,
    ) -> None:
        self.session_id = session_id
        self._requests: dict[str, ApprovalRequest] = {}
        self._cond = threading.Condition()
        self._always: set[tuple[str, str | None]] = set()
        self._on_state_change = on_state_change

    def request(
        self, tool: str, arguments: dict, path: str | None = None
    ) -> ApprovalRequest:
        """发起审批请求；命中 always 覆盖时立即返回已放行请求。"""
        if (tool, path) in self._always:
            return ApprovalRequest(
                session_id=self.session_id,
                tool=tool,
                arguments=arguments,
                path=path,
                status=ApprovalStatus.RESOLVED,
                decision=ApprovalDecision.ALLOW,
                auto=True,
            )
        req = ApprovalRequest(
            session_id=self.session_id, tool=tool, arguments=arguments, path=path
        )
        with self._cond:
            self._requests[req.id] = req
        self._notify_state(True)
        return req

    def wait(self, req: ApprovalRequest, timeout: float | None = None) -> ApprovalRequest:
        """阻塞直到该请求被决议；超时（默认不超时）返回当前状态。"""
        with self._cond:
            self._cond.wait_for(
                lambda: self._requests.get(req.id, req).status == ApprovalStatus.RESOLVED,
                timeout=timeout,
            )
        return self._requests.get(req.id, req)

    def resolve(self, request_id: str, decision: str) -> ApprovalRequest:
        """决议：allow / deny / always。"""
        with self._cond:
            req = self._requests.get(request_id)
            if req is None:
                raise KeyError(f"未知审批请求: {request_id!r}")
            req.status = ApprovalStatus.RESOLVED
            req.decision = decision
            if decision == ApprovalDecision.ALWAYS:
                self._always.add((req.tool, req.path))
            still_pending = self._has_pending()
            self._cond.notify_all()
        if not still_pending:
            self._notify_state(False)
        return req

    def interrupt(self) -> None:
        """中断所有待审批请求（视为拒绝），使阻塞的 wait 立即返回。"""
        with self._cond:
            changed = False
            for req in self._requests.values():
                if req.status == ApprovalStatus.PENDING:
                    req.status = ApprovalStatus.RESOLVED
                    req.decision = ApprovalDecision.DENY
                    changed = True
            if changed:
                self._cond.notify_all()
                self._notify_state(False)

    def pending(self) -> list[ApprovalRequest]:
        with self._cond:
            return [r for r in self._requests.values() if r.status == ApprovalStatus.PENDING]

    def _has_pending(self) -> bool:
        return any(r.status == ApprovalStatus.PENDING for r in self._requests.values())

    def _notify_state(self, waiting: bool) -> None:
        if self._on_state_change:
            self._on_state_change(self.session_id, waiting)
