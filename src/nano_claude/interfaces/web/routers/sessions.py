"""Session management routes — list/create/switch/delete saved sessions."""

import os

from fastapi import APIRouter, HTTPException

from nano_claude.infra.session import Session, session_info

from nano_claude.interfaces.web.serializers import serialize_messages_for_api
from nano_claude.interfaces.web.state import state

router = APIRouter()


@router.get("/api/sessions")
async def api_list_sessions():
    return state.sessions_list()


@router.post("/api/sessions")
async def api_new_session():
    state.new_session()
    return {"ok": True, "current": state.current_info()}


@router.get("/api/sessions/{idx}")
async def api_get_session(idx: int):
    files = state._refresh_sessions()
    if idx < 1 or idx > len(files):
        raise HTTPException(status_code=404, detail="Invalid session")
    info = session_info(files[idx - 1])
    try:
        sess = Session.load(files[idx - 1])
        info["messages"] = serialize_messages_for_api(sess.messages)
    except Exception as e:
        info["messages"] = []
        info["load_error"] = str(e)
    return info


@router.put("/api/sessions/{idx}")
async def api_switch_session(idx: int):
    err = state.load_session_by_index(idx)
    if err:
        raise HTTPException(status_code=400, detail=err)
    return {"ok": True, "current": state.current_info()}


@router.delete("/api/sessions/{idx}")
async def api_delete_session(idx: int):
    err = state.delete_session_by_index(idx)
    if err:
        raise HTTPException(status_code=400, detail=err)
    return {"ok": True, "sessions": state.sessions_list()}


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
