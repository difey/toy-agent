"""会话 CRUD 与消息发送：/sessions。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from mira.web.router.models import CreateSessionBody, InsertMessageBody, SendMessageBody

router = APIRouter(prefix="/api")


def _session_out(s) -> dict:
    return {
        "id": s.id,
        "workspace": s.workspace,
        "agent_type": s.agent_type,
        "model": s.model,
        "title": s.title,
        "status": s.status.value,
        "created_at": s.created_at,
        "meta": s.meta,
    }


@router.get("/sessions")
def list_sessions(request: Request) -> list[dict]:
    return [_session_out(s) for s in request.app.state.client.list_sessions()]


@router.post("/sessions", status_code=201)
def create_session(body: CreateSessionBody, request: Request) -> dict:
    client = request.app.state.client
    try:
        sess = client.create_session(
            Path(body.workspace).resolve(),
            agent_type=body.agent_type,
            model=body.model,
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _session_out(sess)


@router.get("/sessions/{session_id}")
def get_session(session_id: str, request: Request) -> dict:
    try:
        sess = request.app.state.client.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _session_out(sess)


@router.delete("/sessions/{session_id}", status_code=204)
def close_session(session_id: str, request: Request) -> None:
    request.app.state.client.close_session(session_id)


@router.post("/sessions/{session_id}/messages")
def send_message(session_id: str, body: SendMessageBody, request: Request) -> dict:
    client = request.app.state.client
    try:
        thread = client.send_message(
            session_id,
            body.content,
            model=body.model,
            effort=body.effort,
            attachments=body.attachments,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "accepted": thread is not None, "queued": thread is None}


@router.post("/sessions/{session_id}/stop")
def stop_session(session_id: str, request: Request) -> dict:
    """请求停止当前正在生成的回复。"""
    request.app.state.client.stop_message(session_id)
    return {"ok": True}


@router.post("/sessions/{session_id}/insert")
def insert_message(session_id: str, body: InsertMessageBody, request: Request) -> dict:
    """AI 回复期间插入新消息：interrupt=立即斧正 / 排队串行。"""
    client = request.app.state.client
    try:
        return client.enqueue_message(
            session_id,
            body.content,
            model=body.model,
            effort=body.effort,
            interrupt=body.interrupt,
            attachments=body.attachments,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
