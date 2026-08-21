"""观测（基础版）：/sessions/{id}/events。"""

from __future__ import annotations

from fastapi import APIRouter, Request

from mira import paths

router = APIRouter(prefix="/api")


def _read_persisted_events(session_id: str) -> list:
    """在 ~/.mira-code/workspaces/*/sessions/<sid>/ 下读取历史事件（回放源）。"""
    root = paths.workspaces_dir()
    if not root.exists():
        return []
    from mira.telemetry.store import EventStore

    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        store = EventStore(d / "sessions")
        if (store.session_dir(session_id)).exists():
            return list(store.read(session_id))
    return []


@router.get("/sessions/{session_id}/events")
def session_events(session_id: str, request: Request) -> list[dict]:
    """当前活跃会话的事件快照；历史（已持久化）会话从磁盘回退读取。"""
    client = request.app.state.client
    try:
        stream = client.manager.events(session_id)
    except KeyError:
        events = _read_persisted_events(session_id)
        return [e.model_dump() for e in events]
    return [e.model_dump() for e in stream.snapshot()]
