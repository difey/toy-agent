# Web UI

> FastAPI server, SSE streaming, and bundled single-page frontend.
> Last updated: 2026-04-30

## Overview

The Web UI is a **FastAPI server** with **SSE streaming** and a bundled single-page HTML frontend (`index.html`). It provides a browser-based alternative to the TUI, with session management, mode switching, and real-time AI response streaming.

Located in `src/nano_claude/webui.py`, frontend bundled in `src/nano_claude/index.html`.

## Server Architecture

### WebAppState

Shared mutable state (`WebAppState` class) holds:

- `agent` — the `Agent` instance
- `cwd` — working directory
- `session` — current `Session`
- `session_file_ref` — current session file path (wrapped in list for mutability)
- `_sse_queues` — dict of SSE event queues keyed by response_id
- `_running_response_id` — currently active response ID

### FastAPI Routes

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Serve the single-page app (`index.html`) |
| `GET` | `/api/health` | Health check |
| `GET` | `/api/mode` | Get current mode (plan/build) |
| `POST` | `/api/mode` | Set mode (plan/build) |
| `GET` | `/api/sessions` | List all sessions |
| `POST` | `/api/sessions` | Create new session |
| `GET` | `/api/sessions/{idx}` | Get session by index |
| `PUT` | `/api/sessions/{idx}` | Switch to session |
| `DELETE` | `/api/sessions/{idx}` | Delete session |
| `DELETE` | `/api/sessions` | Delete all non-current sessions |
| `POST` | `/api/chat` | Send a message (returns response_id) |
| `GET` | `/api/events` | SSE stream (consumes response_id) |
| `GET` | `/api/current` | Get current session info + messages |
| `POST` | `/api/vscode` | Open cwd in VS Code |

## SSE Streaming

### Flow

1. Client sends `POST /api/chat` with message
2. Server creates a response_id and an `asyncio.Queue`
3. Returns `{"response_id": "..."}` immediately
4. Background task `_execute_chat()` runs the agent:
   - Agent callbacks push events (text, tool_start, tool_result) to the queue
   - On completion, pushes `done` event
5. Client connects to `GET /api/events?response_id=...`:
   - SSE endpoint consumes from the queue
   - Events are sent as SSE `data:` frames
   - Stream ends on `done` or `error` event

### Event Types

| Event | Data Fields | Description |
|-------|-------------|-------------|
| `message` | `role`, `type`, `content` | Text delta or tool event |
| `done` | `{}` | Agent finished |
| `error` | `message` | Error occurred |

### Agent Callback Integration

```python
async def on_text(text: str):
    await _state.push_event("message", {"role": "assistant", "type": "text", "content": text})

async def on_tool_start(call: ToolCall):
    await _state.push_event("message", {
        "role": "assistant", "type": "tool_start",
        "name": call.name, "arguments": call.arguments,
    })

async def on_tool_end(name, title, output):
    await _state.push_event("message", {
        "role": "tool", "type": "tool_result",
        "name": name, "content": output,
    })
```

## Frontend (`index.html`)

Single-page HTML application with:

- **Left sidebar** — lists all saved sessions; click to switch, ✕ to delete, "+ New Session" to start fresh
- **Waterfall chat** — user messages (right-aligned, blue), assistant responses with Markdown rendering (code blocks, lists, bold/italic, links), tool calls and results shown as cards
- **Real-time streaming** — AI responses and tool outputs stream in via SSE
- **Send shortcut** — `⌘+Enter` (Mac) or `Ctrl+Enter` (Windows/Linux); plain `Enter` inserts a newline
- **Dark/Light theme** — auto-detects system preference, toggle with ☀️/🌙 button
- **Mode toggle** — plan/build mode switch button in header

## Session Persistence

Session is saved to disk after each chat round:

```python
# In _execute_chat() finally block:
save_current(session, _state.session_file_ref[0])
```

This ensures the session is always up-to-date even if the server is stopped abruptly.
