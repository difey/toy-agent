"""HTML page routes — serves the built React frontend pages."""

import os
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from nano_claude.core.state import state

router = APIRouter()

_DIST_DIR = Path(__file__).resolve().parent.parent / "static" / "dist"


def _page_title_tag(title: str) -> str:
    """Return a <title> tag with the given text."""
    return f"<title>{title}</title>"


def _cwd_basename() -> str:
    """Return the basename of the current working directory, e.g. 'dir1'."""
    return os.path.basename(state.cwd) if state.cwd else "nanoClaude"


def _read_dist_html(filename: str) -> str:
    """Read a built HTML page from the bundled Vite dist output."""
    filepath = _DIST_DIR / filename
    if not filepath.is_file():
        return (
            "<html><body style='font-family: sans-serif; padding: 40px;'>"
            "<h1>Frontend not built</h1>"
            "<p>The frontend static files have not been built yet.</p>"
            "<p>Run the following commands and restart the server:</p>"
            "<pre>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</pre>"
            "</body></html>"
        )
    return filepath.read_text(encoding="utf-8")


@router.get("/")
async def index() -> HTMLResponse:
    """Serve the main chat app."""
    html = _read_dist_html("index.html")
    dir_name = _cwd_basename()
    html = html.replace("<title>nanoClaude</title>", _page_title_tag(dir_name))
    return HTMLResponse(content=html)


@router.get("/plan-view")
async def plan_view() -> HTMLResponse:
    """Serve the standalone plan document viewer."""
    html = _read_dist_html("plan-view.html")
    dir_name = _cwd_basename()
    html = html.replace(
        "<title>Plan Document - nanoClaude</title>",
        _page_title_tag(f"Plan Document - {dir_name}"),
    )
    return HTMLResponse(content=html)
