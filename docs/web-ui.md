# Web UI

> FastAPI server, SSE streaming, and a bundled React frontend.
> Last updated: 2026-07-19

## Overview

The Web UI is a **FastAPI server** with **SSE streaming** and a **React + Vite multi-page frontend**. It provides a browser-based alternative to the TUI, with session management, mode switching, setup flow, and real-time AI response streaming.

Source code lives in `src/nano_claude/interfaces/web/` for the backend and `frontend/` for the React app. Production assets are built into `src/nano_claude/interfaces/web/static/dist/`, and FastAPI serves those built files directly.

## Server Architecture

### Module Layout

```
frontend/
├── index.html                 ← Vite entry for the main chat app
├── setup.html                 ← Vite entry for the setup wizard
├── plan-view.html             ← Vite entry for the plan viewer
├── vite.config.ts             ← multi-page Vite build config
└── src/
    ├── pages/
    │   ├── chat/              ← main chat page React entry + components
    │   ├── setup/             ← setup wizard React entry + components
    │   └── plan-view/         ← plan viewer React entry + components
    ├── shared/                ← API helpers, shared types, markdown renderer
    └── styles/                ← ported page styles

src/nano_claude/interfaces/web/
├── app.py                     ← FastAPI app factory; mounts built asset chunks
├── state.py                   ← WebAppState class + shared `state` singleton
├── models.py                  ← Pydantic request/response models
├── serializers.py             ← core message → API dict conversion
├── routers/
│   ├── pages.py               ← GET /, /setup, /plan-view (serves built HTML)
│   ├── system.py              ← health, mode, vscode, plan-doc, current
│   ├── sessions.py            ← session CRUD
│   ├── setup.py               ← setup wizard endpoints
│   └── chat.py                ← chat, stop, events (SSE), question/permission responses
└── services/
    ├── chat_service.py        ← wires core Agent callbacks to SSE events
    ├── setup_service.py       ← builds/updates the core Agent from config
    └── plan_service.py        ← reads/resolves the latest plan markdown
```

Routers only handle HTTP concerns (request parsing, status codes) and delegate business logic to `services/`, which in turn drive the `core.Agent` and `infra` session helpers.

### Built asset serving

- `frontend/` is the editable source for the web UI.
- `npm run build` emits static files into `src/nano_claude/interfaces/web/static/dist/`.
- `app.py` mounts `static/dist/assets/` for JS/CSS chunks.
- `pages.py` reads and returns the built `index.html`, `setup.html`, and `plan-view.html`.
- The `/` route still preserves the existing `needs_setup()` behavior by serving setup content when the user has not configured nanoClaude yet.

### WebAppState

Shared mutable state (`WebAppState` class) holds:

- `agent` — the `Agent` instance
- `cwd` — working directory
- `session` — current `Session`
- `session_file_ref` — current session file path (wrapped in list for mutability)
- `_sse_queues` — dict of SSE event queues keyed by response_id
- `_running_response_id` — currently active response ID
- `_running` — boolean indicating a chat is currently in progress
- `_running_task` — reference to the asyncio.Task for cancellation

### FastAPI Routes

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Serve the main chat app, or setup if configuration is still required |
| `GET` | `/setup` | Serve the setup wizard |
| `GET` | `/plan-view` | Serve the standalone plan viewer |
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
| `POST` | `/api/stop` | Request graceful stop of the current AI response |
| `GET` | `/api/events` | SSE stream (consumes response_id) |
| `GET` | `/api/current` | Get current session info + messages |
| `POST` | `/api/vscode` | Open cwd in VS Code |
| `GET` | `/api/workspace-panel` | Get right-panel data: modified files + all plan docs |

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
    await state.push_event("message", {"role": "assistant", "type": "text", "content": text})

async def on_tool_start(call: ToolCall):
    await state.push_event("message", {
        "role": "assistant", "type": "tool_start",
        "name": call.name, "arguments": call.arguments,
    })

async def on_tool_end(name, title, output):
    await state.push_event("message", {
        "role": "tool", "type": "tool_result",
        "name": name, "content": output,
    })
```

## Frontend

The React frontend preserves the existing UX and API contract while moving the implementation into typed modules:

- **Main chat app** — sidebar session management, waterfall chat, markdown-rendered assistant replies, tool cards, sub-agent flow panels, right-side workspace panel (modified files tree + plan docs), stop button, theme toggle, mobile sidebar, toast notifications, question dialogs, permission dialogs, and keyboard shortcuts
- **Setup wizard** — 3-step model/API key flow backed by `/api/setup-status` and `/api/setup`
- **Plan viewer** — standalone markdown page backed by `/api/plan-doc`, including download support
- **Markdown rendering** — uses npm packages [`marked`](https://github.com/markedjs/marked) and [`DOMPurify`](https://github.com/cure53/DOMPurify), bundled by Vite instead of loaded from CDNs

## Building the frontend

```bash
cd frontend
npm install
npm run build
```

This writes the production bundle to:

```text
src/nano_claude/interfaces/web/static/dist/
```

Because Python packaging does not run a frontend build automatically, the built `static/dist/` output must remain checked into the repository for releases and installs.

## Session Persistence

Session is saved to disk after each chat round:

```python
# In _execute_chat() finally block:
save_current(session, state.session_file_ref[0])
```

This ensures the session is always up-to-date even if the server is stopped abruptly.
