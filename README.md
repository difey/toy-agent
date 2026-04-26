# toy-agent

A Python CLI coding assistant that uses LLM-powered tools to complete coding tasks from natural language input.

```bash
$ toy-agent "用 FastAPI 写一个 hello world 服务"
   Let me create a FastAPI hello world service.
  [bash [install fastapi]] pip install fastapi uvicorn...
  [write [main.py]] Wrote 350 bytes to main.py
   Done! Created main.py, run with `uvicorn main:app`.
```

## Quick Start

```bash
cd toy-agent/

# Install globally (run from anywhere)
uv tool install .

# First run — setup wizard guides you through model + API key
toy-agent
```

Configuration is saved to `~/.my_code/config.toml`. Run `toy-agent --setup` to reconfigure.

## Usage

### Single turn

```bash
toy-agent "create a python script"
toy-agent "add tests to main.py" --cwd /tmp/my-project
toy-agent "..." --model deepseek-v4-pro
```

### Interactive mode

```bash
$ toy-agent --cwd ./my-project
ToyAgent interactive mode. Type /help for commands, Ctrl+C to exit.
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
| `/sessions` | List all saved sessions |
| `/session <n>` | Switch to session n |
| `/exit` | Exit |

Session history is auto-saved to `<cwd>/.session/<timestamp>.json`.

## Providers

Provider is auto-detected from the model name prefix:

| Prefix | Provider | API Key Env | Base URL |
|--------|----------|------------|----------|
| `deepseek-*` | DeepSeek | `DEEPSEEK_API_KEY` | `https://api.deepseek.com/v1` |
| `gpt-*`, `o1-*`, `o3-*`, `o4-*` | OpenAI | `OPENAI_API_KEY` | (default) |
| `claude-*` | Anthropic | `ANTHROPIC_API_KEY` | `https://api.anthropic.com/v1` |
| (custom) | Ollama | `OLLAMA_BASE_URL` | `http://localhost:11434/v1` |

For Ollama, set `TOY_AGENT_PROVIDER=ollama`. Use `TOY_AGENT_API_KEY` as a fallback key for any provider.

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `DEEPSEEK_API_KEY` | DeepSeek API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `TOY_AGENT_API_KEY` | Fallback key for any provider |
| `TOY_AGENT_MODEL` | Default model |
| `TOY_AGENT_PROVIDER` | Force provider |

## Available Tools

| Tool | Description |
|------|-------------|
| `bash` | Execute shell commands (persistent session, 120s timeout, 50KB output cap) |
| `read` | Read files with line numbers, supports offset/limit for large files |
| `write` | Create or overwrite files (auto-creates parent directories) |
| `edit` | Exact string replacement in files (prefer edit over write for modifications) |
| `glob` | Filename pattern search (e.g. `**/*.py`) |
| `grep` | Content search with regex (uses ripgrep when available, Python fallback) |

## Run Tests

```bash
cd toy-agent/
uv run -m pytest tests/ -v
```
