# Tool System

> Tool registry, base classes, tool descriptions, and execution flow.
> Last updated: 2026-04-30

## Overview

The tool system is defined in `src/nano_claude/tool.py` with individual tool implementations in `src/nano_claude/tools/`.

## Architecture

```
ToolRegistry (tool.py)
  ├── register(BaseTool) → adds tool by name
  ├── get(name) → returns tool instance
  ├── filtered_copy(names) → returns new registry with only specified tools (used for plan mode)
  ├── to_openai_tools() → converts to OpenAI function-calling format
  └── get_tools_prompt(year) → builds tool descriptions from *.txt files
```

Each tool extends `BaseTool`:

```python
class BaseTool:
    name: str           # tool name (matches method name in LLM function calling)
    description: str    # from .txt file
    
    async def execute(arguments: dict, ctx: ToolContext) -> ToolExecResult
```

### ToolContext

Carries contextual information to each tool execution:

```python
ToolContext:
    cwd: str                         # resolved working directory
    permission_callback              # called before dangerous operations
    ask_user_callback                # called for question tool
    mode: str                        # "plan" or "build"
```

### ToolExecResult

```python
ToolExecResult:
    output: str      # text output returned to LLM
    title: str       # short label displayed in UI ("bash", "wrote 350 bytes", etc.)
```

## Available Tools (12 total)

> In **plan mode**, only `read`, `write`, `edit`, `glob`, `grep`, `question`, `todowrite` are available.

| Tool | Description | File |
|------|-------------|------|
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
| `apply_patch` | Batch editing: add/update/delete multiple files in one call (unified diff) | `apply_patch.py` |

## Tool Descriptions (`.txt` files)

Each tool has a corresponding `.txt` file in `src/nano_claude/tools/` (e.g., `bash.txt`, `read.txt`). These descriptions are read at startup and injected into the system prompt via `ToolRegistry.get_tools_prompt()`.

Format example (`bash.txt`):

```
Execute a shell command. The command runs in a persistent shell session with preserved working directory state.
Commands timeout after 120 seconds. Output is truncated at 50KB.
```

The year parameter in `get_tools_prompt(year)` is used for date-sensitive descriptions (e.g., "The current year is {year}").

## Registration

Tools are registered in `cli.py`:

```python
def _build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(BashTool())
    registry.register(ReadTool())
    # ... all 12 tools
    return registry
```

## Execution Flow

When the LLM returns tool calls:

1. `Agent._execute_tool_calls()` iterates each call
2. Looks up tool by name: `self.tools.get(call.name)`
3. Calls `await tool.execute(call.arguments, ctx)`
4. On success: wraps result in `ToolExecResult`, fires `on_tool_end` callback
5. On error: wraps exception message in `ToolExecResult` with title "error"
6. Appends `ToolResult` message to session
7. Runs `session._compact()` to manage token limits

## Adding a New Tool

1. Create `<name>.py` in `src/nano_claude/tools/` with a class extending `BaseTool`
2. Create `<name>.txt` with the tool description (for system prompt)
3. Register in `cli.py` → `_build_registry()`
4. Add to `tools/__init__.py`
5. Add tests in `tests/test_agent.py`
