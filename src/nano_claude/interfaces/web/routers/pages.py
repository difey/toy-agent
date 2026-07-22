"""HTML page routes — serves the built React frontend pages."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from nano_claude.interfaces.web.services.setup_service import needs_setup

router = APIRouter()

_DIST_DIR = Path(__file__).resolve().parent.parent / "static" / "dist"


def _read_dist_html(filename: str) -> str:
    """Read a built HTML page from the bundled Vite dist output."""
    return (_DIST_DIR / filename).read_text(encoding="utf-8")


@router.get("/")
async def index() -> HTMLResponse:
    """Serve the main app. Redirect to setup content if not configured."""
    if needs_setup():
        return HTMLResponse(content=_read_dist_html("setup.html"))
    return HTMLResponse(content=_read_dist_html("index.html"))


@router.get("/setup")
async def setup_page() -> HTMLResponse:
    """Serve the setup wizard page."""
    return HTMLResponse(content=_read_dist_html("setup.html"))


@router.get("/plan-view")
async def plan_view() -> HTMLResponse:
    """Serve the standalone plan document viewer."""
    return HTMLResponse(content=_read_dist_html("plan-view.html"))
