# Architecture Overview

> Agent loop, plan/build modes, system prompts, and mode switching.
> Last updated: 2026-04-30

## Agent Loop (`agent.py`)

`Agent.run()` / `Agent.run_stream()` implement the core loop:

1. Send messages to LLM
2. Receive text + tool calls
3. Execute tools (bash, read, write, etc.)
4. Append results to session
5. Repeat until LLM responds without tool calls

The stream variant (`run_stream`) sends text deltas to the UI in real-time via callbacks (`on_text_delta`, `on_tool_start`, `on_tool_end`).

### Key Methods

| Method | Description |
|--------|-------------|
| `_build_system_prompt(cwd)` | Builds system prompt with `{cwd}`, `{platform}`, `{date}`, `{tools}` |
| `_get_mode_tools()` | Returns filtered `ToolRegistry` based on current mode |
| `set_mode(mode)` | Toggles between `"plan"` and `"build"`, updates tool set + system prompt |
| `_execute_tool_calls(calls, ctx, sess)` | Iterates tool calls, executes via `ToolRegistry`, appends results to session |
| `_get_or_create_session(session, cwd)` | Ensures session has latest system prompt as first message |

### Callbacks

Agent accepts callbacks for UI integration:

- `permission_callback(tool, target, reason) → str` — called before dangerous operations
- `ask_user_callback(header, question, options, multiple) → list[str]` — called for `question` tool
- `on_text_delta(text)` — streaming text chunks
- `on_tool_start(call)` — tool call began
- `on_tool_end(name, title, output)` — tool call completed

## Plan Mode & Build Mode

The agent supports two operational modes:

| Mode | System Prompt | Available Tools | Purpose |
|------|---------------|-----------------|---------|
| **Build** (default) | `SYSTEM_PROMPT` | All 12 tools | Implement code, run commands |
| **Plan** | `PLAN_SYSTEM_PROMPT` | read, write, edit, glob, grep, question, todowrite | Discuss requirements only |

### Plan Mode Restrictions

Defined in `agent.py`:

```python
PLAN_MODE_TOOLS = {"read", "write", "edit", "glob", "grep", "question", "todowrite"}
```

In plan mode:
- Agent cannot write source code (`.py`, `.js`, `.ts`, etc.)
- Agent cannot run shell commands (`bash` tool is excluded)
- Agent is instructed to produce a `.md` requirements document
- All tools in `PLAN_MODE_TOOLS` remain available

### System Prompts

**`SYSTEM_PROMPT`** (build mode): Full prompt with path rules, code conventions, response style guidelines, and all tool descriptions.

**`PLAN_SYSTEM_PROMPT`** (plan mode): Restricted prompt that instructs the agent to only discuss requirements, write `.md` files, and remind the user to switch to build mode when ready.

Mode switching preserves the full conversation history. When switching from plan to build, the agent sees the entire planning discussion.

### "执行" Workflow

Located in `ui.py` — `_handle_submit()`:

1. After each plan mode agent response, `_find_latest_plan()` scans `cwd` for `.md` files (excluding README.md, agents.md, etc.)
2. The newest `.md` plan content is auto-appended to the output
3. If user types `执行`, the UI:
   - Calls `agent.set_mode("build")`
   - Reads the plan file content
   - Injects it as context in a user message
   - The agent then implements according to the plan

### Mode Switching (TUI)

Commands in `ui.py`:

- `/plan` → `Agent.set_mode("plan")` + insert transition message
- `/build` → `Agent.set_mode("build")` + insert transition message

### Mode Switching (Web UI)

API endpoint `POST /api/mode` in `webui.py`:

```python
_state.agent.set_mode(mode)
_state.session.messages.append(UserMessage(content="[Mode changed to ...]"))
```

### System Prompt Template

Both prompts are formatted with:

```python
template.format(
    cwd=cwd,
    platform=platform.system(),
    date=datetime.now().strftime("%a %b %d %Y"),
    tools=tools_prompt,  # from *.txt files
)
```
