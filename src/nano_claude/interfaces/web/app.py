"""Web UI server for nanoClaude — FastAPI app factory + Uvicorn startup."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from nano_claude.core.state import state
from nano_claude.interfaces.web.routers import chat, diffs, pages, providers, sessions, system

_DIST_ASSETS_DIR = Path(__file__).resolve().parent / "static" / "dist" / "assets"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan — nothing special to do yet."""
    yield


def create_app() -> FastAPI:
    """Build the FastAPI application and mount all routers."""
    app = FastAPI(
        title="nanoClaude",
        version="0.2.0",
        lifespan=lifespan,
    )
    app.mount("/static/dist/assets", StaticFiles(directory=_DIST_ASSETS_DIR, check_dir=False), name="web-dist-assets")
    app.include_router(pages.router)
    app.include_router(system.router)
    app.include_router(sessions.router)
    app.include_router(providers.router)
    app.include_router(chat.router)
    app.include_router(diffs.router)
    return app


app = create_app()


# ── Server startup ──────────────────────────────────────────────────────

def start_web_ui(
    cwd: str,
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    open_browser: bool = True,
) -> None:
    """Start the web server using Uvicorn. 只接受 cwd，state 自行初始化其余部分。"""
    state.initialize(cwd=cwd)

    import webbrowser

    url = f"http://{host}:{port}"
    print(f"\n  🌐 Web UI started at {url}")
    if open_browser:
        webbrowser.open(url)
    print("  Press Ctrl+C to stop.\n")

    import uvicorn
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )
