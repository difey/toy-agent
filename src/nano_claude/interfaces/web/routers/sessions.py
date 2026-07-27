"""Session management routes — list/create/switch/delete saved sessions."""

import os

from fastapi import APIRouter, HTTPException

from nano_claude.infra.session import Session, session_info

from nano_claude.interfaces.web.serializers import serialize_messages_for_api
from nano_claude.interfaces.web.services.diff_service import (
    list_checkpoints_for_session,
    RollbackError,
)
from nano_claude.interfaces.web.state import state

router = APIRouter()


@router.get("/api/sessions")
async def api_list_sessions():
    return state.sessions_list()


@router.post("/api/sessions/fork")
async def api_fork_session(body: dict):
    message_index = body.get("message_index")
    if message_index is None or not isinstance(message_index, int):
        raise HTTPException(status_code=400, detail="message_index is required (int)")
    return {"ok": True, "current": state.fork_session(message_index)}

@router.post("/api/sessions/rollback")
async def api_rollback_session(body: dict):
    message_index = body.get("message_index")
    if message_index is None or not isinstance(message_index, int):
        raise HTTPException(status_code=400, detail="message_index is required (int)")
    try:
        result = state.rollback_session(message_index)
        return {
            "ok": True,
            "current": result,
            "skipped_files": result.get("skipped_files", []),
            "errors": result.get("errors", []),
        }
    except (ValueError, RuntimeError, RollbackError) as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/api/sessions")
async def api_new_session():
    state.new_session()
    return {"ok": True, "current": state.current_info()}


@router.get("/api/sessions/{name}")
async def api_get_session(name: str):
    filepath = state._find_session_by_name(name)
    if filepath is None:
        raise HTTPException(status_code=404, detail="Invalid session")
    info = session_info(filepath)
    try:
        sess = Session.load(filepath)
        info["messages"] = serialize_messages_for_api(sess.messages)
    except Exception as e:
        info["messages"] = []
        info["load_error"] = str(e)
    info["diff_summaries"] = list_checkpoints_for_session(
        state.cwd, os.path.basename(filepath),
    )
    return info


@router.put("/api/sessions/{name}")
async def api_switch_session(name: str):
    err = state.load_session_by_name(name)
    if err:
        raise HTTPException(status_code=400, detail=err)
    return {"ok": True, "current": state.current_info()}


@router.delete("/api/sessions/{name}")
async def api_delete_session(name: str):
    err = state.delete_session_by_name(name)
    if err:
        raise HTTPException(status_code=400, detail=err)
    return {
        "ok": True,
        "current": state.current_info(),
        "sessions": state.sessions_list(),
    }


@router.delete("/api/sessions")
async def api_delete_all_sessions():
    files = state._refresh_sessions()
    current_abs = os.path.abspath(state.session_file_ref[0])
    deleted = 0
    for f in files:
        if os.path.abspath(f) != current_abs:
            try:
                os.remove(f)
                deleted += 1
            except OSError:
                pass
    return {"ok": True, "deleted": deleted, "sessions": state.sessions_list()}
