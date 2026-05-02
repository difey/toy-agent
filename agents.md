# nanoClaude — Agent Context

> Concise project overview for code agent context resets.
> Last updated: 2026-05-02

nanoClaude is a Python CLI coding assistant. It accepts natural language tasks and uses an LLM with various tools to complete them autonomously.

```bash
nano-claude "create a python script"        # Single turn
nano-claude --cwd ./my-project              # Interactive TUI
nano-claude --web                           # Web UI (recommended)
nano-claude --plan                          # Plan mode (discuss before coding)
```

## Repository Structure

```
src/nano_claude/
├── cli.py       # CLI entrypoint, session init (auto-resume last session)
├── ui.py        # Interactive TUI (prompt_toolkit), mode switching, "执行" workflow
├── webui.py     # Web UI server (FastAPI + SSE)
├── index.html   # Web UI frontend (single-page app)
├── agent.py     # Core Agent class — LLM loop, plan/build mode system prompts
├── session.py   # Session management, auto-compact, auto-title, persistence
├── message.py   # Message data classes
├── config.py    # Provider config detection (OpenAI/DeepSeek/Anthropic/Ollama)
├── setup.py     # First-run setup wizard
├── tool.py      # ToolRegistry, BaseTool, ToolContext, ToolExecResult
└── tools/       # 14 tool implementations + .txt descriptions
```

## Plan Mode & Build Mode

Two operational modes: **build** (default, all tools) and **plan** (restricted to `.md` and discussion). Switch via `/plan` and `/build` in TUI, or the mode toggle in Web UI. Type `执行` in plan mode to auto-switch to build with the plan content injected as context.

→ See [docs/architecture-overview.md](docs/architecture-overview.md)

## Available Tools (14 total)

Tools: `bash`, `read`, `write`, `edit`, `glob`, `grep`, `webfetch`, `websearch`, `codesearch`, `todowrite`, `question`, `apply_patch`, `skill`, `delegate`.

Plan mode restricts to: `read`, `write`, `edit`, `glob`, `grep`, `question`, `todowrite`, `skill`.

→ See [docs/tool-system.md](docs/tool-system.md)

## Session System

Sessions auto-save to `<cwd>/.session/<timestamp>.json`. Auto-compact at 100K tokens (summarize or drop oldest turn). Auto-resume most recent session on startup.

→ See [docs/session-system.md](docs/session-system.md)

## Web UI

FastAPI server with SSE streaming. Session sidebar, waterfall chat, Markdown rendering, dark/light theme. Interactive question dialogs with queuing. File permission approval for out-of-cwd file access (Allow/Deny/Always Allow, 120s timeout). Start with `nano-claude --web`.

→ See [docs/web-ui.md](docs/web-ui.md)

## Interactive TUI

prompt_toolkit full-screen TUI with state machine (INPUT → RUNNING → AWAITING_PERMISSION → AWAITING_QUESTION). Slash commands, auto-completion, asyncio.Future-based callbacks.

→ See [docs/ui-architecture.md](docs/ui-architecture.md)

## Development

- Python 3.11+, [uv](https://docs.astral.sh/uv/) package manager
- Key deps: `openai`, `click`, `rich`, `prompt-toolkit`, `httpx`, `markdownify`, `beautifulsoup4`, `fastapi`, `uvicorn`
- Tests: `uv run -m pytest tests/ -v`
- Build: `uv build`
