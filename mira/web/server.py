"""FastAPI 应用工厂 + uvicorn 入口。

启动：python -m mira.web.server [--port PORT]
端口优先级：--port > 环境变量 MIRA_WEB_PORT > 默认 8000
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from mira.api.client import AppClient
from mira.web.router import router as rest_router
from mira.web.ws import ws_router

WEBUI_DIR = Path(__file__).resolve().parent / "webui"


def create_app(client: AppClient | None = None) -> FastAPI:
    app = FastAPI(title="Mira Code", version="0.2.0")
    app.state.client = client or AppClient()
    app.include_router(rest_router)
    app.include_router(ws_router)
    if WEBUI_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(WEBUI_DIR)), name="webui")

        @app.get("/", include_in_schema=False)
        async def index() -> FileResponse:
            return FileResponse(str(WEBUI_DIR / "index.html"))

    return app


app = create_app()


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(prog="mira.web.server", description="启动 Mira Code Web 服务器")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MIRA_WEB_PORT", "8000")),
        help="监听端口（默认取 $MIRA_WEB_PORT，否则 8000）",
    )
    args = parser.parse_args()

    uvicorn.run(
        "mira.web.server:app",
        host="127.0.0.1",
        port=args.port,
        reload=False,
        # Ctrl+C 优雅关闭：等待活跃连接（浏览器保持的 WebSocket 轮询）关闭，超时强制退出
        timeout_graceful_shutdown=3,
    )


if __name__ == "__main__":
    main()
