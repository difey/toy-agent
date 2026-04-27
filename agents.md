# nanoClaude — Agent Context

> This file provides project context for when the code agent's context is reset.
> Last updated: 2026-04-27

## Project Overview

nanoClaude is a Python CLI coding assistant. It accepts natural language tasks and uses an LLM with various tools to complete them autonomously. Think of it as a lightweight, CLI-first Cursor/Devin alternative.

```bash
# Single turn
nano-claude "用 FastAPI 写一个 hello world 服务"

# Interactive mode
nano-claude --cwd ./my-project
```

The agent works by:
1. Receiving a user prompt (via CLI or interactive shell)
2. Sending it (plus conversation history) to an LLM (OpenAI/DeepSeek/Anthropic/Ollama)
3. The LLM responds with text and/or tool calls
4. The agent executes tool calls (bash, read, write, edit, etc.)
5. Results feed back to the LLM for the next turn
6. Repeats until the LLM responds without tool calls (task done)

## Repository Structure

```
toy-agent/
├── pyproject.toml              # Project metadata, deps, scripts entrypoint
├── README.md                   # User-facing docs
├── agents.md                   # THIS FILE — agent context
├── uv.lock                     # Lock file
├── .gitignore
├── docs/                       # Architecture documentation
│   └── ui-architecture.md      # Interactive TUI design and state machine
├── .session/                   # Saved session JSON files (auto-generated)
│   └── 2026-04-27T*.json
├── src/
│   └── nano_claude/
│       ├── __init__.py         # Empty package init
│       ├── cli.py              # CLI entrypoint (click), session helpers, main()
│       ├── ui.py               # InteractiveUI class, TUI layout, SlashCompleter, key bindings
│       ├── agent.py            # Core Agent class — LLM loop, tool execution, system prompt
│       ├── session.py          # Session management, message history, token accounting, session utilities
│       ├── message.py          # Data classes: SystemMessage, UserMessage, AssistantMessage, ToolResult, ToolCall, StreamChunk variants
│       ├── config.py           # Provider config detection and resolution
│       ├── setup.py            # First-run setup wizard (config.toml)
│       ├── tool.py             # Base tool classes: ToolRegistry, ToolContext, ToolExecResult, BaseTool
│       ├── llm.py              # LLM client — OpenAI-compatible chat/chat_stream
│       └── tools/              # Individual tool implementations
│           ├── __init__.py     # Tool imports
│           ├── bash.py
│           ├── read.py
│           ├── write.py
│           ├── edit.py
│           ├── glob_.py
│           ├── grep.py
│           ├── webfetch.py
│           ├── websearch.py
│           ├── codesearch.py
│           ├── todowrite.py
│           ├── question.py
│           ├── apply_patch.py
│           ├── exa_client.py   # Shared Exa AI HTTP client for websearch + codesearch
│           └── (name).txt      # Tool descriptions injected into system prompt
└── tests/
    └── test_agent.py           # All tests in one file
```

## Key Architecture Decisions

### Interactive UI (`ui.py` — `InteractiveUI`)

The interactive mode uses a **persistent full-screen TUI** built with `prompt_toolkit`'s `Application` framework, replacing the old `PromptSession.prompt()` approach. Key design:

- **Always-visible footer** — session title, CWD, and AI running state never disappear
- **State machine** — `INPUT → RUNNING → AWAITING_PERMISSION → AWAITING_QUESTION`
- **`asyncio.Future`-based callbacks** — permission requests and AI questions integrated into the UI via key bindings, not raw stdin
- **Callback override** — agent callbacks are temporarily redirected to append output to the UI buffer during AI execution

See [`docs/ui-architecture.md`](docs/ui-architecture.md) for detailed documentation.

### Agent Loop (`agent.py`)

- `Agent.run()` / `Agent.run_stream()` implement the core loop:
  - Send messages to LLM → receive text + tool calls → execute tools → append results → repeat
  - Stream variant sends text deltas to the UI in real-time via callbacks
- System prompt is built dynamically with `{cwd}`, `{platform}`, `{date}`, and `{tools}` (from `*.txt` files)

### Session System (`session.py`)

- Sessions maintain message history across turns
- **Auto-title**: Session derives a short title (~40 chars) from the first user message's first meaningful line
- Title is persisted in session JSON files and restored on load
- Bottom toolbar displays the session title instead of the filename; token count hidden
- Auto-compact when total tokens exceed `max_tokens` (default 100K)
  - With summarizer: summarize oldest user+assistant turn into a `[Conversation summary]` SystemMessage
  - Without summarizer: drop oldest turn entirely
- Sessions auto-save to `<cwd>/.session/<timestamp>.json`
- Interactive mode supports `/session new`, `/session <n>`, `/session delete <n|all>`, `/sessions`

### Provider System (`config.py`)

- Provider auto-detected from model name prefix:
  - `deepseek-*` → DeepSeek (DEEPSEEK_API_KEY)
  - `gpt-*`, `o1-*`, `o3-*`, `o4-*` → OpenAI (OPENAI_API_KEY)
  - `claude-*` → Anthropic (ANTHROPIC_API_KEY)
  - other → defaults to OpenAI, or force with `NANO_CLAUDE_PROVIDER=ollama`
- User config stored in `~/.nano_claude/config.toml`

### LLM Client (`llm.py`)

- OpenAI-compatible API (works with OpenAI, DeepSeek, Anthropic via proxy, Ollama)
- `chat()` — synchronous response with tool support
- `chat_stream()` — streaming response with typed chunks (TextDelta, ToolCallBegin, ToolCallArgDelta, ReasoningDelta)

### Tool System (`tool.py` + `tools/`)

- `ToolRegistry` registers tools, converts to OpenAI function-calling format
- `BaseTool` subclass per tool, each with `execute(arguments, ctx) -> ToolExecResult`
- Tool descriptions come from `*.txt` files in `tools/` directory (injected into system prompt)
- `ToolContext` carries `cwd`, `permission_callback`, `ask_user_callback`

## Available Tools (12 total)

| Tool | Description | Key file |
|------|-------------|----------|
| `bash` | Execute shell commands (120s timeout, 50KB output cap, persistent session) | `bash.py` |
| `read` | Read files with line numbers, offset/limit | `read.py` |
| `write` | Create/overwrite files, auto-creates parent dirs | `write.py` |
| `edit` | Exact string replacement (prefer over write for modifications) | `edit.py` |
| `glob` | Filename pattern search (e.g. `**/*.py`) | `glob_.py` |
| `grep` | Content search with regex (ripgrep or Python fallback) | `grep.py` |
| `webfetch` | Fetch URLs, auto-upgrade HTTP→HTTPS, format: markdown/text/html | `webfetch.py` |
| `websearch` | Real-time web search via Exa AI | `websearch.py` |
| `codesearch` | Programming search via Exa Code API | `codesearch.py` |
| `todowrite` | Structured task list for multi-step progress (persisted to `~/.nano_claude/todos.json`) | `todowrite.py` |
| `question` | Ask user for input (preferences, clarifications, decisions) | `question.py` |
| `apply_patch` | Batch edit: add/update/delete multiple files in one call (unified diff format) | `apply_patch.py` |

## Development

### Dependencies

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) for package management
- Key deps: `openai`, `click`, `rich`, `prompt-toolkit`, `httpx`, `markdownify`, `beautifulsoup4`

### Running Tests

```bash
cd toy-agent/
uv run -m pytest tests/ -v
```

### Code Conventions (from system prompt)

- Follow existing code style
- Clear, descriptive variable names
- Minimal comments
- Be concise in responses
- Never generate/assume URLs unless confident

### Build

```bash
uv build
```

## Common Tasks

### Adding a new tool
1. Create `<name>.py` in `src/nano_claude/tools/` with a class extending `BaseTool`
2. Create `<name>.txt` with the tool description (for system prompt)
3. Register the tool in `cli.py` → `_build_registry()`
4. Add to `tools/__init__.py`
5. Add tests in `tests/test_agent.py`

### Adding a new provider
1. Add entry in `pyproject.toml` under `[tool.nano-claude.providers.<name>]`
2. Update `detect_provider()` in `config.py`
3. Update README.md tables

### Session format (JSON)
```json
{
  "max_tokens": 100000,
  "messages": [
    {"type": "SystemMessage", "data": {"content": "..."}},
    {"type": "UserMessage", "data": {"content": "..."}},
    {"type": "AssistantMessage", "data": {"content": "...", "tool_calls": [...]}},
    {"type": "ToolResult", "data": {"tool_call_id": "...", "content": "..."}}
  ]
}
```
