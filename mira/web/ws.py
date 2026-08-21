"""WebSocket 事件透传：订阅指定 session，按 last_seq 增量推送。

- 客户端连接后首条消息发 {"last_seq": N}（断线重连补偿）；
- 服务端轮询 EventStream 快照，把 seq > last_seq 的事件逐条透传（与 CLI 拿到的事件同构）。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

ws_router = APIRouter()

POLL_INTERVAL_S = 0.1


@ws_router.websocket("/api/ws/sessions/{session_id}")
async def ws_events(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    last_seq = 0
    try:
        try:
            msg = await asyncio.wait_for(websocket.receive_json(), timeout=2)
            last_seq = int((msg or {}).get("last_seq", 0))
        except (asyncio.TimeoutError, ValueError, KeyError):
            last_seq = 0

        client = websocket.app.state.client
        stream = client.manager.events(session_id)
        while True:
            for event in stream.snapshot():
                if event.seq > last_seq:
                    await websocket.send_json(event.model_dump())
                    last_seq = event.seq
            # 同时等待轮询间隔 / 客户端断开 / 服务器关闭：客户端断开立即退出，
            # 避免连接一直挂着拖慢服务优雅关闭
            receive_task = asyncio.ensure_future(websocket.receive())
            sleep_task = asyncio.ensure_future(asyncio.sleep(POLL_INTERVAL_S))
            done, pending = await asyncio.wait(
                [receive_task, sleep_task], return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            for task in done:
                msg = task.result()
                if isinstance(msg, dict) and msg.get("type") == "websocket.disconnect":
                    return
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001  (session 关闭等：静默断开)
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
