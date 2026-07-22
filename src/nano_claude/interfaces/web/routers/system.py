"""System/utility routes — health check, mode toggle, current session info, VS Code, plan doc."""

import subprocess

from fastapi import APIRouter, HTTPException

from nano_claude.core.message import UserMessage

from nano_claude.interfaces.web.services.plan_service import get_plan_doc, resolve_latest_plan
from nano_claude.interfaces.web.state import state

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
            resolve_latest_plan(state.cwd)

        state.agent.set_mode(mode)
        # Insert transition message instead of clearing session
        if mode == "plan":
            msg = "[Mode changed to Plan mode. You can now only discuss requirements and write/edit .md files. Do NOT write any source code or run shell commands.]"
        else:
            msg = "[Mode changed to Build mode. All tools are now available. You can implement code, run commands, and make changes.]"
        state.session.messages.append(UserMessage(content=msg))
    return {"mode": mode}


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
async def api_plan_doc():
    """Return the latest plan document from .session/ directory."""
    return get_plan_doc(state.cwd)


@router.get("/api/current")
async def api_current():
    return state.current_info()
