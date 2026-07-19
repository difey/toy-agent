"""HTML page routes — serves the bundled single-page app and static pages."""

from importlib.resources import files

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from nano_claude.interfaces.web.services.setup_service import needs_setup

router = APIRouter()


def _get_index_html() -> str:
    """Read the index.html bundled with the package."""
    return (files("nano_claude.interfaces.web.static") / "index.html").read_text(encoding="utf-8")


def _get_setup_html() -> str:
    """Read the setup.html bundled with the package."""
    return (files("nano_claude.interfaces.web.static") / "setup.html").read_text(encoding="utf-8")


def _get_plan_view_html() -> str:
    """Read the plan-view.html bundled with the package."""
    return (files("nano_claude.interfaces.web.static") / "plan-view.html").read_text(encoding="utf-8")


@router.get("/")
async def index() -> HTMLResponse:
    """Serve the single-page app. Redirect to setup if not configured."""
    if needs_setup():
        return HTMLResponse(content=_get_setup_html())
    return HTMLResponse(content=_get_index_html())


@router.get("/setup")
async def setup_page() -> HTMLResponse:
    """Serve the setup wizard page."""
    return HTMLResponse(content=_get_setup_html())


@router.get("/plan-view")
async def plan_view() -> HTMLResponse:
    """Serve a standalone page that displays the latest plan document."""
    return HTMLResponse(content=_get_plan_view_html())
