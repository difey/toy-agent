"""工作区：列表 / 重命名 / 删除。"""

from __future__ import annotations

import json
import os
import shutil

from fastapi import APIRouter, HTTPException, Request

from mira import paths
from mira.web.router.models import RenameWorkspaceBody

router = APIRouter(prefix="/api")


def _list_workspaces() -> list[dict]:
    """扫描 ~/.mira-code/workspaces/ 列出工作区及其会话（含标题，来自 meta.json）。"""
    root = paths.workspaces_dir()
    if not root.exists():
        return []
    out: list[dict] = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        sessions_root = d / "sessions"
        sids = (
            sorted(p.name for p in sessions_root.iterdir() if p.is_dir())
            if sessions_root.exists()
            else []
        )
        sessions = []
        for sid in sids:
            title = ""
            meta = d / "sessions" / sid / "meta.json"
            if meta.exists():
                try:
                    title = json.loads(meta.read_text(encoding="utf-8")).get("title", "")
                except Exception:  # noqa: BLE001
                    title = ""
            sessions.append({"id": sid, "title": title})
        path = None
        meta = d / "workspace.json"
        if meta.exists():
            try:
                path = json.loads(meta.read_text(encoding="utf-8")).get("path")
            except Exception:  # noqa: BLE001
                path = None
        out.append({"id": d.name, "path": path, "sessions": sessions})
    return out


@router.get("/workspaces")
def workspaces(request: Request) -> list[dict]:
    live = {s.workspace: s for s in request.app.state.client.list_sessions()}
    result = _list_workspaces()
    # 补上/更新内存中的活跃会话（标题以内存为准，可能尚未落盘）
    for ws, s in live.items():
        w = paths.workspace_id(ws)
        existing = next((x for x in result if x["id"] == w), None)
        if existing is None:
            result.append({"id": w, "path": ws, "sessions": [{"id": s.id, "title": s.title}]})
        else:
            entry = next((x for x in existing["sessions"] if x["id"] == s.id), None)
            if entry is not None:
                entry["title"] = s.title
            else:
                existing["sessions"].append({"id": s.id, "title": s.title})
    return result


@router.post("/workspaces/{ws_id}/rename")
def rename_workspace(ws_id: str, body: RenameWorkspaceBody) -> dict:
    """重命名工作区：{新名}_{原路径哈希}（哈希由原始路径决定，保持不变）。"""
    d = paths.workspaces_dir() / ws_id
    if not d.exists():
        raise HTTPException(status_code=404, detail=f"工作区不存在: {ws_id}")
    path = None
    meta = d / "workspace.json"
    if meta.exists():
        try:
            path = json.loads(meta.read_text(encoding="utf-8")).get("path")
        except Exception:  # noqa: BLE001
            path = None
    if not path:
        raise HTTPException(status_code=400, detail="该工作区缺少路径信息，无法重命名")
    hash_tail = paths.workspace_id(path).split("_", 1)[1]
    new_id = f"{body.name.strip()}_{hash_tail}"
    new_dir = paths.workspaces_dir() / new_id
    if new_dir.exists() and new_dir != d:
        raise HTTPException(status_code=409, detail=f"目标名称已存在: {new_id}")
    os.rename(d, new_dir)
    return {"id": new_id, "path": path}


@router.delete("/workspaces/{ws_id}", status_code=204)
def delete_workspace(ws_id: str) -> None:
    """删除工作区目录（含其下所有 session / telemetry 数据）。"""
    d = paths.workspaces_dir() / ws_id
    if d.exists():
        shutil.rmtree(d)
