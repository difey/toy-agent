# nanoClaude

A Python CLI coding assistant that uses LLM-powered tools to complete coding tasks from natural language input.

```bash
$ nano-claude "用 FastAPI 写一个 hello world 服务"
   Let me create a FastAPI hello world service.
  [bash [install fastapi]] pip install fastapi uvicorn...
  [write [main.py]] Wrote 350 bytes to main.py
   Done! Created main.py, run with `uvicorn main:app`.
```

## Installation

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (Python package manager)

### Install globally

```bash
cd nanoClaude/

# Install as a global CLI tool (run from anywhere)
uv tool install .

# Verify installation
uv tool list
```

### Upgrade

> ⚠️ **Note**: When upgrading, the tool is reinstalled from source. If you've pulled the latest code (e.g. via `git pull`), make sure to rebuild so that any web UI changes are correctly applied.

```bash
cd nanoClaude/
uv build
uv tool install --reinstall .
```

### Uninstall

```bash
uv tool uninstall nanoClaude
```

## Quick Start

```bash
# First run — setup wizard guides you through model + API key
nano-claude
```

Configuration is saved to `~/.nano_claude/config.toml`. Run `nano-claude --setup` to reconfigure.

## Usage

### Single turn

```bash
nano-claude "create a python script"
nano-claude "add tests to main.py" --cwd /tmp/my-project
nano-claude "..." --model deepseek-v4-pro
```

### Plan Mode & Build Mode

nanoClaude supports two operational modes in interactive and web UI:

| Mode | Icon | Purpose | Available Tools |
|------|------|---------|-----------------|
| **Build mode** (default) | 🔨 | Implement code, run commands, make changes | All tools (bash, read, write, edit, glob, grep, etc.) |
| **Plan mode** | 📋 | Discuss requirements, write specifications only | Restricted: read, write (`.md` only), edit, glob, grep, question, todowrite |

**Plan mode** is designed for requirement analysis. The agent can only read files and write/edit `.md` files — it cannot write source code or run shell commands. This lets you discuss and document what needs to be built before any code is written.

**Build mode** unlocks all tools, allowing the agent to implement code, run commands, and make changes.

**Starting in plan mode:**
```bash
# Start interactive mode in plan mode
nano-claude --plan
```

**Switching modes interactively:**
- `/plan` — switch to plan mode (discuss requirements only)
- `/build` — switch to build mode (implement code)

Mode switching preserves the full conversation history. When switching from plan to build, the agent sees the entire planning discussion.

**"执行" workflow:** After the agent produces a plan (`.md` file) in plan mode, the plan content is automatically displayed at the end of each response. Type `执行` to automatically switch to build mode with the plan content injected as context — the agent will implement according to the plan.

### Web UI mode (recommended)

Start a browser-based UI with a session sidebar and waterfall chat display:

```bash
# Start web UI on default port 8080
nano-claude --web

# Custom port
nano-claude --web --port 9090
```

The web UI opens automatically in your browser at `http://127.0.0.1:8080`.

**Features:**
- **Left sidebar** — lists all saved sessions; click to switch, ✕ to delete, "+ New Session" to start fresh
- **Waterfall chat** — user messages (right-aligned, blue), assistant responses with Markdown rendering (code blocks, lists, bold/italic, links), tool calls and results shown as cards
- **Real-time streaming** — AI responses and tool outputs stream in as they're generated via SSE (Server-Sent Events)
- **Send shortcut** — `⌘+Enter` (Mac) or `Ctrl+Enter` (Windows/Linux) to send; plain `Enter` inserts a newline
- **Dark/Light theme** — auto-detects system preference, toggle with the ☀️/🌙 button
- **Multi-turn conversations** — same session management as TUI, auto-saved to `<cwd>/.session/`

### Interactive mode (TUI)

```bash
$ nano-claude --cwd ./my-project
nanoClaude interactive mode. Type /help for commands, Ctrl+C to exit.
> write a hello world script
  [write [hello.py]] Wrote 120 bytes to hello.py
   Done!
> /exit
```

| Command | Description |
|---------|-------------|
| `/help` | Show help |
| `/clear` | Clear conversation history |
| `/tokens` | Show token usage |
| `/session` | Show current session info |
| `/session new` | Start a new session |
| `/sessions` | Interactive session list (↑↓→← Esc) |
| `/sessions new` | Start a new session |
| `/sessions <n>` | Switch to session n |
| `/sessions delete <n>` | Delete session n |
| `/sessions delete all` | Delete all saved sessions |
| `/plan` | Switch to plan mode (discuss requirements only) |
| `/build` | Switch to build mode (implement code) |
| `/vscode` | Open current directory in VS Code |
| `/exit` | Exit |

Session history is auto-saved to `<cwd>/.session/<timestamp>.json`. On startup, nanoClaude automatically resumes the most recent session from the same working directory, so your conversation history persists across restarts.

## Providers

Provider is auto-detected from the model name prefix:

| Prefix | Provider | API Key Env | Base URL |
|--------|----------|------------|----------|
| `deepseek-*` | DeepSeek | `DEEPSEEK_API_KEY` | `https://api.deepseek.com/v1` |
| `gpt-*`, `o1-*`, `o3-*`, `o4-*` | OpenAI | `OPENAI_API_KEY` | (default) |
| `claude-*` | Anthropic | `ANTHROPIC_API_KEY` | `https://api.anthropic.com/v1` |
| (custom) | Ollama | `OLLAMA_BASE_URL` | `http://localhost:11434/v1` |

For Ollama, set `NANO_CLAUDE_PROVIDER=ollama`. Use `NANO_CLAUDE_API_KEY` as a fallback key for any provider.

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `DEEPSEEK_API_KEY` | DeepSeek API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `NANO_CLAUDE_API_KEY` | Fallback key for any provider |
| `NANO_CLAUDE_MODEL` | Default model |
| `NANO_CLAUDE_PROVIDER` | Force provider |

## Available Tools

| Tool | Description |
|------|-------------|
| `bash` | Execute shell commands (persistent session, 120s timeout, 50KB output cap) |
| `read` | Read files with line numbers, supports offset/limit for large files |
| `write` | Create or overwrite files (auto-creates parent directories) |
| `edit` | Exact string replacement in files (prefer edit over write for modifications) |
| `glob` | Filename pattern search (e.g. `**/*.py`) |
| `grep` | Content search with regex (uses ripgrep when available, Python fallback) |
| `webfetch` | Fetch content from URLs with format options (markdown, text, html); auto-upgrades HTTP to HTTPS |
| `websearch` | Real-time web search using Exa AI; provides up-to-date information beyond the model's knowledge cutoff |
| `codesearch` | Programming-oriented search using Exa Code API; returns code examples, docs, and API references |
| `todowrite` | Create and manage a structured task list for tracking multi-step progress (persisted to `~/.nano_claude/todos.json`) |
| `question` | Ask the user for input to gather preferences, clarify ambiguous instructions, or get decisions |
| `apply_patch` | Structured batch editing: add/update/delete multiple files in one call using unified diff format |

## Run Tests

```bash
cd nanoClaude/
uv run -m pytest tests/ -v
```
