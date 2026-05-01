"""Web UI server for nanoClaude — FastAPI + SSE streaming + modern frontend."""

import asyncio
import json
import os
import subprocess
import traceback
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse, HTMLResponse
from pydantic import BaseModel

from nano_claude.agent import Agent
from nano_claude.session import Session, list_sessions, save_current, session_info, session_path
from nano_claude.message import ToolCall, UserMessage


# ── Pydantic models ──────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str


class SessionInfo(BaseModel):
    path: str
    name: str
    title: str
    messages: int
    tokens: int
    preview: str
    index: int = 0
    is_current: bool = False


class CurrentInfo(BaseModel):
    path: str
    name: str
    title: str
    messages: int
    tokens: int
    preview: str
    is_current: bool = True
    index: int = 1
    message_list: list[dict] = []


class ApiResponse(BaseModel):
    ok: bool = True
    error: str | None = None


# ── In-memory shared state ──────────────────────────────────────────────

class WebAppState:
    """Shared mutable state for the web UI server."""
    def __init__(self):
        self.agent: Agent | None = None
        self.cwd: str = ""
        self.session: Session | None = None
        self.session_file_ref: list[str] = [""]
        # SSE queues: keyed by response_id
        self._sse_queues: dict[str, asyncio.Queue] = {}
        self._running_response_id: str | None = None
        # Pending question state (for question tool)
        self._pending_question: dict | None = None  # {future, header, question, options, multiple}

    # ── session helpers ─────────────────────────────────────────────────

    def _refresh_sessions(self) -> list[str]:
        return list_sessions(self.cwd)

    def _get_current_idx(self) -> int | None:
        files = self._refresh_sessions()
        current_abs = os.path.abspath(self.session_file_ref[0])
        for i, f in enumerate(files):
            if os.path.abspath(f) == current_abs:
                return i + 1  # 1-based
        return None

    def sessions_list(self) -> list[dict]:
        files = self._refresh_sessions()
        current_idx = self._get_current_idx()
        result = []
        for i, f in enumerate(files):
            info = session_info(f)
            info["index"] = i + 1
            info["is_current"] = (i + 1 == current_idx)
            result.append(info)
        return result

    def load_session_by_index(self, index: int) -> str | None:
        """Load a session by 1-based index. Returns error message or None."""
        files = self._refresh_sessions()
        if index < 1 or index > len(files):
            return f"Invalid session number: {index}"
        target = files[index - 1]
        if os.path.abspath(target) == os.path.abspath(self.session_file_ref[0]):
            return None  # already current
        save_current(self.session, self.session_file_ref[0])
        try:
            new_session = Session.load(target)
        except Exception as e:
            return f"Failed to load session: {e}"
        self.session.messages.clear()
        self.session.messages.extend(new_session.messages)
        self.session.title = new_session.title
        self.session_file_ref[0] = target
        return None

    def delete_session_by_index(self, index: int) -> str | None:
        """Delete a session by 1-based index. Returns error message or None."""
        files = self._refresh_sessions()
        if index < 1 or index > len(files):
            return f"Invalid session number: {index}"
        target = files[index - 1]
        if os.path.abspath(target) == os.path.abspath(self.session_file_ref[0]):
            return "Cannot delete current active session."
        try:
            os.remove(target)
            return None
        except OSError as e:
            return f"Error: {e}"

    def new_session(self) -> None:
        save_current(self.session, self.session_file_ref[0])
        self.session.messages.clear()
        self.session.title = ""
        self.session_file_ref[0] = session_path(self.cwd)

    def current_info(self) -> dict:
        info = session_info(self.session_file_ref[0])
        info["is_current"] = True
        info["index"] = self._get_current_idx() or 1
        info["messages"] = _serialize_messages_for_api(self.session.messages)
        info["mode"] = self.agent.mode if self.agent else "build"
        return info

    # ── SSE helpers ─────────────────────────────────────────────────────

    def create_sse_queue(self, response_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._sse_queues[response_id] = q
        self._running_response_id = response_id
        return q

    def get_sse_queue(self, response_id: str) -> asyncio.Queue | None:
        return self._sse_queues.get(response_id)

    def remove_sse_queue(self, response_id: str) -> None:
        self._sse_queues.pop(response_id, None)
        if self._running_response_id == response_id:
            self._running_response_id = None

    async def push_event(self, event: str, data: dict) -> None:
        """Push an event to the currently running SSE queue."""
        if self._running_response_id:
            q = self._sse_queues.get(self._running_response_id)
            if q:
                await q.put((event, data))


# ── Globally shared state instance ──────────────────────────────────────

_state = WebAppState()


# ── FastAPI app setup ───────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan — nothing special to do yet."""
    yield


app = FastAPI(
    title="nanoClaude",
    version="0.2.0",
    lifespan=lifespan,
)


# ── SSE streaming ──────────────────────────────────────────────────────

async def _sse_event_generator(response_id: str) -> AsyncGenerator[str, None]:
    """Async generator that yields SSE-formatted events from the queue."""
    queue = _state.get_sse_queue(response_id)
    if queue is None:
        yield f"event: error\ndata: {json.dumps({'message': 'Response stream not found'})}\n\n"
        return

    try:
        while True:
            event, data = await queue.get()
            payload = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            yield payload
            if event == "done" or event == "error":
                break
    except (asyncio.CancelledError, GeneratorExit):
        pass
    finally:
        _state.remove_sse_queue(response_id)


async def _run_chat(message: str) -> str:
    """Schedule the agent to run in background. Returns the response_id immediately."""
    agent = _state.agent
    session = _state.session

    response_id = f"chat_{id(session)}_{len(session.messages)}_{id(message)}"
    _state.create_sse_queue(response_id)

    # Run the agent in a background task so the response_id is returned immediately
    asyncio.ensure_future(_execute_chat(message, response_id))
    return response_id


async def _execute_chat(message: str, response_id: str) -> None:
    """Actually execute the agent chat in the background, pushing SSE events."""
    agent = _state.agent
    session = _state.session
    cwd = _state.cwd

    # Set up agent callbacks to push events
    original_on_text = agent.on_text_delta
    original_on_tool_start = agent.on_tool_start
    original_on_tool_end = agent.on_tool_end
    original_permission = agent.permission_callback
    original_ask_user = agent.ask_user_callback

    async def on_text(text: str):
        await _state.push_event("message", {"role": "assistant", "type": "text", "content": text})
        if original_on_text:
            result = original_on_text(text)
            if asyncio.iscoroutine(result):
                await result

    async def on_tool_start(call: ToolCall):
        await _state.push_event("message", {
            "role": "assistant",
            "type": "tool_start",
            "name": call.name,
            "arguments": call.arguments,
        })
        if original_on_tool_start:
            result = original_on_tool_start(call)
            if asyncio.iscoroutine(result):
                await result

    async def on_tool_end(name: str, title: str, output: str):
        await _state.push_event("message", {
            "role": "tool",
            "type": "tool_result",
            "name": name,
            "title": title,
            "content": output,
        })
        if original_on_tool_end:
            result = original_on_tool_end(name, title, output)
            if asyncio.iscoroutine(result):
                await result

    async def permission_callback(tool: str, target: str, reason: str) -> str:
        return "allow"

    async def ask_user_callback(header: str, question: str, options: list[dict], multiple: bool) -> list[str]:
        await _state.push_event("question", {
            "header": header,
            "question": question,
            "options": options,
            "multiple": multiple,
        })
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        _state._pending_question = {
            "future": future,
            "header": header,
            "question": question,
            "options": options,
            "multiple": multiple,
        }
        try:
            result = await asyncio.wait_for(future, timeout=300)
            return result
        except asyncio.TimeoutError:
            return ["(skipped)"]
        finally:
            _state._pending_question = None

    agent.on_text_delta = on_text
    agent.on_tool_start = on_tool_start
    agent.on_tool_end = on_tool_end
    agent.permission_callback = permission_callback
    agent.ask_user_callback = ask_user_callback

    try:
        await agent.run_stream(message, cwd, session=session)
        await _state.push_event("done", {})
    except asyncio.CancelledError:
        await _state.push_event("done", {})
    except Exception:
        tb = traceback.format_exc()
        await _state.push_event("error", {"message": tb})
    finally:
        agent.on_text_delta = original_on_text
        agent.on_tool_start = original_on_tool_start
        agent.on_tool_end = original_on_tool_end
        agent.permission_callback = original_permission
        agent.ask_user_callback = original_ask_user
        save_current(session, _state.session_file_ref[0])


# ── API Routes ──────────────────────────────────────────────────────────

@app.get("/")
async def index() -> HTMLResponse:
    """Serve the single-page app."""
    return HTMLResponse(content=_get_index_html())


@app.get("/plan-view")
async def plan_view() -> HTMLResponse:
    """Serve a standalone page that displays the latest plan document."""
    return HTMLResponse(content=_get_plan_view_html())


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.2.0"}


@app.get("/api/mode")
async def api_get_mode():
    return {"mode": _state.agent.mode if _state.agent else "build"}


@app.post("/api/mode")
async def api_set_mode(body: dict):
    mode = body.get("mode", "build")
    if mode not in ("plan", "build"):
        raise HTTPException(status_code=400, detail="Mode must be 'plan' or 'build'")
    if _state.agent and _state.session:
        # When switching from build → plan, mark the latest plan as resolved
        if mode == "plan" and _state.agent.mode == "build":
            _resolve_latest_plan(_state.cwd)

        _state.agent.set_mode(mode)
        # Insert transition message instead of clearing session
        if mode == "plan":
            msg = "[Mode changed to Plan mode. You can now only discuss requirements and write/edit .md files. Do NOT write any source code or run shell commands.]"
        else:
            msg = "[Mode changed to Build mode. All tools are now available. You can implement code, run commands, and make changes.]"
        _state.session.messages.append(UserMessage(content=msg))
    return {"mode": mode}


@app.get("/api/sessions")
async def api_list_sessions():
    return _state.sessions_list()


@app.post("/api/sessions")
async def api_new_session():
    _state.new_session()
    return {"ok": True, "current": _state.current_info()}


@app.get("/api/sessions/{idx}")
async def api_get_session(idx: int):
    files = _state._refresh_sessions()
    if idx < 1 or idx > len(files):
        raise HTTPException(status_code=404, detail="Invalid session")
    info = session_info(files[idx - 1])
    try:
        sess = Session.load(files[idx - 1])
        info["messages"] = _serialize_messages_for_api(sess.messages)
    except Exception as e:
        info["messages"] = []
        info["load_error"] = str(e)
    return info


@app.put("/api/sessions/{idx}")
async def api_switch_session(idx: int):
    err = _state.load_session_by_index(idx)
    if err:
        raise HTTPException(status_code=400, detail=err)
    return {"ok": True, "current": _state.current_info()}


@app.delete("/api/sessions/{idx}")
async def api_delete_session(idx: int):
    err = _state.delete_session_by_index(idx)
    if err:
        raise HTTPException(status_code=400, detail=err)
    return {"ok": True, "sessions": _state.sessions_list()}


@app.delete("/api/sessions")
async def api_delete_all_sessions():
    files = _state._refresh_sessions()
    current_abs = os.path.abspath(_state.session_file_ref[0])
    deleted = 0
    for f in files:
        if os.path.abspath(f) != current_abs:
            try:
                os.remove(f)
                deleted += 1
            except OSError:
                pass
    return {"ok": True, "deleted": deleted, "sessions": _state.sessions_list()}


@app.post("/api/vscode")
async def api_open_vscode():
    """Open the current working directory in VS Code."""
    cwd = _state.cwd
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


@app.get("/api/plan-doc")
async def api_plan_doc():
    """Return the latest plan document from .session/ directory."""
    from pathlib import Path
    import os
    cwd = _state.cwd
    session_dir = Path(cwd) / ".session"
    if not session_dir.is_dir():
        return {"exists": False, "filename": None, "content": None, "modified": None}
    md_files = sorted(session_dir.glob("*.md"), key=lambda f: os.path.getmtime(f))
    if not md_files:
        return {"exists": False, "filename": None, "content": None, "modified": None}
    latest = md_files[-1]
    return {
        "exists": True,
        "filename": latest.name,
        "content": latest.read_text(encoding="utf-8"),
        "modified": os.path.getmtime(latest),
        "size": latest.stat().st_size,
    }


@app.get("/api/current")
async def api_current():
    return _state.current_info()


@app.post("/api/chat")
async def api_chat(req: ChatRequest):
    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    # Push user message as event
    await _state.push_event("message", {"role": "user", "type": "text", "content": message})

    response_id = await _run_chat(message)
    return {"response_id": response_id}


@app.post("/api/question-answer")
async def api_question_answer(body: dict):
    if _state._pending_question is None:
        raise HTTPException(status_code=400, detail="No pending question")
    answer = body.get("answer")
    if answer is None:
        raise HTTPException(status_code=400, detail="Missing 'answer' field")
    if isinstance(answer, str):
        answer = [answer]
    future = _state._pending_question["future"]
    if not future.done():
        future.set_result(answer)
    return {"ok": True}


@app.get("/api/events")
async def api_events(response_id: str = Query(...)):
    queue = _state.get_sse_queue(response_id)
    if queue is None:
        raise HTTPException(status_code=404, detail="Response stream not found")

    return StreamingResponse(
        _sse_event_generator(response_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Message serialization for API ───────────────────────────────────────

def _serialize_messages_for_api(messages) -> list[dict]:
    """Convert session messages to a format suitable for the web frontend."""
    result = []
    for msg in messages:
        from nano_claude.message import SystemMessage, UserMessage, AssistantMessage, ToolResult
        if isinstance(msg, SystemMessage):
            continue  # skip system messages in display
        elif isinstance(msg, UserMessage):
            content = msg.content if isinstance(msg.content, str) else json.dumps(msg.content, ensure_ascii=False)
            result.append({"role": "user", "type": "text", "content": content})
        elif isinstance(msg, AssistantMessage):
            if msg.content:
                result.append({"role": "assistant", "type": "text", "content": msg.content})
            for tc in msg.tool_calls:
                result.append({
                    "role": "assistant",
                    "type": "tool_start",
                    "name": tc.name,
                    "arguments": tc.arguments,
                    "tool_call_id": tc.id,
                })
        elif isinstance(msg, ToolResult):
            result.append({
                "role": "tool",
                "type": "tool_result",
                "name": msg.tool_name or "",
                "content": msg.content[:2000],
                "tool_call_id": msg.tool_call_id,
            })
    return result


# ── HTML frontend (single-page app) ─────────────────────────────────────


def _get_index_html() -> str:
    """Read the index.html bundled with the package."""
    from importlib.resources import files
    return (files("nano_claude") / "index.html").read_text(encoding="utf-8")


def _get_plan_view_html() -> str:
    """Read the plan-view.html bundled with the package."""
    from importlib.resources import files
    return (files("nano_claude") / "plan-view.html").read_text(encoding="utf-8")


def _resolve_latest_plan(cwd: str) -> None:
    """Rename the latest .md file in .session/ to .md.resolved."""
    from pathlib import Path
    import os
    session_dir = Path(cwd) / ".session"
    if not session_dir.is_dir():
        return
    md_files = sorted(session_dir.glob("*.md"), key=lambda f: os.path.getmtime(f))
    if not md_files:
        return
    latest = str(md_files[-1])
    resolved_path = latest + ".resolved"
    if os.path.exists(latest):
        os.rename(latest, resolved_path)


# ── Server startup ──────────────────────────────────────────────────────

def start_web_ui(
    agent: Agent,
    cwd: str,
    session: Session,
    session_file: str,
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    open_browser: bool = True,
) -> None:
    """Start the web server using Uvicorn. This is meant to be run from cli.py."""
    _state.agent = agent
    _state.cwd = cwd
    _state.session = session
    _state.session_file_ref[0] = session_file

    import webbrowser

    url = f"http://{host}:{port}"
    print(f"\n  🌐 Web UI started at {url}")
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
