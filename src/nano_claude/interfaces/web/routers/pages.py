"""HTML page routes — serves the built React frontend pages."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_DIST_DIR = Path(__file__).resolve().parent.parent / "static" / "dist"


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
    return HTMLResponse(content=_read_dist_html("index.html"))


@router.get("/plan-view")
async def plan_view() -> HTMLResponse:
    """Serve the standalone plan document viewer."""
    return HTMLResponse(content=_read_dist_html("plan-view.html"))
