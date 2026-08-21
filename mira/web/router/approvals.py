"""审批（HITL）：/sessions/{id}/approvals。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from mira.web.router.models import ResolveApprovalBody

router = APIRouter(prefix="/api")


@router.get("/sessions/{session_id}/approvals")
def pending_approvals(session_id: str, request: Request) -> list[dict]:
    return request.app.state.client.pending_approvals(session_id)


@router.post("/sessions/{session_id}/approvals/{request_id}")
def resolve_approval(
    session_id: str, request_id: str, body: ResolveApprovalBody, request: Request
) -> dict:
    try:
        return request.app.state.client.resolve_approval(
            session_id, request_id, body.decision
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
