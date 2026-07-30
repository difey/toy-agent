"""System/utility routes — health check, mode toggle, current session info, VS Code, plan doc."""

import subprocess

from fastapi import APIRouter, HTTPException, Query

from nano_claude.core.message import SystemMessage, UserMessage
from nano_claude.core.state import state

router = APIRouter()


@router.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.2.0"}


@router.get("/api/mode")
async def api_get_mode():
    return {"mode": state.agent.mode if state.agent else "build"}


@router.post("/api/mode")
async def api_set_mode(body: dict):
    mode = body.get("mode", "build")
    if mode not in ("plan", "build"):
        raise HTTPException(status_code=400, detail="Mode must be 'plan' or 'build'")
    if state.agent is None:
        raise HTTPException(status_code=400, detail="请先完成配置")
    if state.agent and state.session:
        # When switching from build → plan, mark the latest plan as resolved
        if mode == "plan" and state.agent.mode == "build":
            state.resolve_latest_plan()

        state.agent.set_mode(mode)
        # Insert transition message instead of clearing session
        if mode == "plan":
            msg = "[Mode changed to Plan mode. You can now only discuss requirements and write/edit .md files. Do NOT write any source code or run shell commands.]"
        else:
            msg = "[Mode changed to Build mode. All tools are now available. You can implement code, run commands, and make changes.]"
        collapsed = await state.session.add_message(SystemMessage(content=msg))
    return {"mode": mode, "collapsed_count": collapsed, "current": state.current_info()}


@router.post("/api/vscode")
async def api_open_vscode():
    """Open the current working directory in VS Code."""
    cwd = state.cwd
    try:
        subprocess.Popen(["code", cwd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"ok": True}
    except FileNotFoundError:
        # `code` command not found; try macOS `open` with VS Code app
        try:
            subprocess.Popen(
                ["open", "-a", "Visual Studio Code", cwd],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return {"ok": True}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"VS Code not found: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/plan-doc")
async def api_plan_doc(filename: str | None = Query(default=None)):
    """Return a selected plan document from the session directory."""
    return state.get_plan_doc(filename)


@router.get("/api/workspace-panel")
async def api_workspace_panel(active_diff: str | None = Query(default=None)):
    """Return plan-doc and modified-file metadata for the right-side panel."""
    return state.workspace_view(active_diff)


@router.get("/api/current")
async def api_current(active_diff: str | None = Query(default=None)):
    return state.current_view(active_diff)
