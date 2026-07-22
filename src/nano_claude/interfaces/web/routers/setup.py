"""Setup wizard routes — configure model/API key via the web UI."""

from fastapi import APIRouter, HTTPException

from nano_claude.interfaces.web.models import SetupRequest
from nano_claude.interfaces.web.services.setup_service import apply_setup, resolve_api_key, setup_status
from nano_claude.interfaces.web.state import state

router = APIRouter()


@router.get("/api/setup-status")
async def api_setup_status():
    """Check if the user has saved config (~/.nano_claude/config.toml)."""
    return setup_status()


@router.post("/api/setup")
async def api_setup(body: SetupRequest):
    """Save user configuration from the web setup wizard."""
    model = body.model.strip()
    if not model:
        raise HTTPException(status_code=400, detail="模型名称不能为空")

    api_key = resolve_api_key(body.api_key)
    if not api_key:
        raise HTTPException(status_code=400, detail="API Key 不能为空，请在表单中输入或设置环境变量")

    try:
        apply_setup(state, model, api_key)
        return {"ok": True, "model": model}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存配置失败: {e}")
