# Session System

> Session management, message history, token accounting, and persistence.
> Last updated: 2026-05-17

## Overview

Sessions manage the conversation history across turns. Each session maintains a list of `Message` objects, handles auto-compaction when token limits are exceeded, and persists to JSON files.

Located in `src/nano_claude/infra/session.py`.

## Session Class

### Constructor

```python
Session(
    system_prompt: str = "",
    max_tokens: int = 100_000,
    summarizer: Summarizer | None = None,
    title: str = "",
)
```

### Message Types

| Class | Role |
|-------|------|
| `SystemMessage` | System prompt (always first message) |
| `UserMessage` | User input |
| `AssistantMessage` | AI response text + tool calls |
| `ToolResult` | Tool execution output |

### Auto-Title

Session derives a short title (~40 chars) from the first user message's first meaningful line. If a summarizer is available, it uses AI to generate a concise title (in Chinese). Fallback: truncate the first non-empty line.

Titles are persisted in session JSON files and restored on load.

## Token Management

### Token Estimation

`estimate_tokens(text)` — rough estimation: `max(1, len(text) // 4)`.

### Auto-Compact

When total tokens exceed `max_tokens` (default 100K), the session automatically compacts:

**With summarizer:** Summarize the oldest user+assistant turn into a `[Conversation summary]` SystemMessage. Preserves key decisions, code changes, file paths, and tool actions.

**Without summarizer:** Drop the oldest user+assistant turn entirely.

The compaction loop runs until tokens are under the limit or only one turn remains.

## Persistence

Sessions are stored in `~/.nano_claude/sessions/` (user home directory, alongside `config.toml`).

### Index File

An index file (`~/.nano_claude/sessions/index.json`) maps resolved cwd paths to stable hash-based folder names:

```json
{
  "/Users/me/project-a": "a1b2c3d4e5f6g7h8",
  "/Users/me/project-b": "i9j0k1l2m3n4o5p6"
}
```

Each session file lives at `~/.nano_claude/sessions/<hash>/<timestamp>.json`. Plan `.md` files also reside in the same directory.

### Session Path

```python
def session_path(cwd: str) -> str:
    ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    session_dir = _ensure_session_dir(cwd)
    return os.path.join(session_dir, f"{ts}.json")
```

### Auto-Save

Session is saved to `~/.nano_claude/sessions/<hash>/<timestamp>.json`:
- On program exit (`interfaces/cli/cli.py` finally block)
- On `/sessions new` command
- On switching to another session (`/sessions <n>`)
- After each chat round in Web UI (`interfaces/web/services/chat_service.py` _execute_chat finally)

### Auto-Resume

On startup (`interfaces/cli/cli.py`), the program checks for existing session files:

```python
existing = list_sessions(resolved_cwd)
if existing:
    last_path = existing[-1]  # most recent (sorted by name = timestamp)
    session = Session.load(last_path)
    session_file = last_path  # reuse same file path
```

This prevents the sessions directory from accumulating files across restarts. Only explicit `/sessions new` creates a new file.

### Migration

On first run after upgrading, old `<cwd>/.session/` files are automatically migrated to the new home-directory location via `migrate_old_sessions()`.

### Save Guard

```python
def save_current(session, filepath):
    if session.messages:  # only save non-empty sessions
        session.save(filepath)
```

### JSON Format

```json
{
  "max_tokens": 100000,
  "title": "Session title",
  "system_prompt": "You are nanoClaude...",
  "messages": [
    {"type": "SystemMessage", "data": {"content": "..."}},
    {"type": "UserMessage", "data": {"content": "..."}},
    {"type": "AssistantMessage", "data": {"content": "...", "tool_calls": [...]}},
    {"type": "ToolResult", "data": {"tool_call_id": "...", "content": "..."}}
  ]
}
```

## Utility Functions

| Function | Description |
|----------|-------------|
| `session_path(cwd)` | Generate timestamped file path in `~/.nano_claude/sessions/<hash>/` |
| `list_sessions(cwd)` | List all `.json` files in the session directory (sorted) |
| `get_session_dir(cwd)` | Return the session directory path for a given cwd (for plan files, etc.) |
| `session_info(filepath)` | Get session metadata (title, message count, tokens) |
| `save_current(session, filepath)` | Save if session has messages |
| `migrate_old_sessions(cwd)` | Migrate files from `<cwd>/.session/` to home-directory storage |

## Commands

| Command | Behavior |
|---------|----------|
| `/sessions` | Show interactive session list (↑↓→← Esc) |
| `/sessions new` | Save current, start fresh session with new file |
| `/sessions <n>` | Save current, load session n from file |
| `/sessions delete <n>` | Delete session file n |
| `/sessions delete all` | Delete all non-current session files |
| `/clear` | Clear messages (no save, no new file) |
