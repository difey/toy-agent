"""Web UI server for nanoClaude — FastAPI app factory + Uvicorn startup."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from nano_claude.core.agent import Agent
from nano_claude.infra.session import Session

from nano_claude.interfaces.web.routers import chat, pages, sessions, setup, system
from nano_claude.interfaces.web.state import state


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
    app.include_router(pages.router)
    app.include_router(system.router)
    app.include_router(sessions.router)
    app.include_router(setup.router)
    app.include_router(chat.router)
    return app


app = create_app()


# ── Server startup ──────────────────────────────────────────────────────

def start_web_ui(
    agent: Agent | None,
    cwd: str,
    session: Session,
    session_file: str,
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    open_browser: bool = True,
) -> None:
    """Start the web server using Uvicorn. This is meant to be run from cli.py."""
    state.agent = agent
    state.cwd = cwd
    state.session = session
    state.session_file_ref[0] = session_file

    import webbrowser

    url = f"http://{host}:{port}"
    if agent:
        print(f"\n  🌐 Web UI started at {url}")
    else:
        print(f"\n  🌐 Web UI started at {url} (setup mode — configure via browser)")
    if open_browser:
        webbrowser.open(url)
    print(f"  Press Ctrl+C to stop.\n")

    import uvicorn
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )
