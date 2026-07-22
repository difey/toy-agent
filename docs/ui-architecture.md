# Interactive UI Architecture

> This document explains the prompt_toolkit-based TUI (Text User Interface) used in nanoClaude's interactive mode.
> Last updated: 2026-04-30

## Overview

The interactive mode uses `prompt_toolkit`'s `Application` framework to build a **persistent full-screen TUI**. Unlike the old `PromptSession.prompt()` approach (where the UI only existed while waiting for input), the Application runs continuously throughout the entire interaction lifecycle — user input, AI response, and tool execution.

```
┌──────────────────────────────────────────────────┐
│  Application runs persistently (full-screen)     │
│  ┌────────────────────────────────────────┐     │
│  │  Output Area (scrollable conversation)  │     │
│  │                                        │     │
│  │  > user message                        │     │
│  │  AI response...                        │     │
│  │    [bash] tool output                   │     │
│  │  ───                                   │     │
│  │  > next message                        │     │
│  ├────────────────────────────────────────┤     │
│  │  Input Area (single line, auto-complete)│     │
│  ├────────────────────────────────────────┤     │
│  │  Status Bar (ALWAYS VISIBLE)           │     │
│  │  Session: xxx  CWD: /path  [🔄 AI...] │     │
│  └────────────────────────────────────────┘     │
└──────────────────────────────────────────────────┘
```

## Key Class: `InteractiveUI`

Located in `src/nano_claude/interfaces/cli/ui.py`, `InteractiveUI` encapsulates the entire TUI. It was extracted from `interfaces/cli/cli.py` as a separate module to keep the codebase organized.

### Layout Structure

```
FloatContainer
├── HSplit (main content)
│   ├── Window (output area)       ← BufferControl(focusable=False, read_only)
│   │   └── Scrollable, wrap_lines=True
│   ├── Window (input area)        ← BufferControl(complete_while_typing=True)
│   │   └── height=1
│   └── Window (status bar)        ← FormattedTextControl (dynamic)
│       └── height=1, always visible
└── Float (completion menu)
    └── CompletionsMenu            ← Shown when input buffer has focus + completions
```

The layout is wrapped in a `FloatContainer` to support the floating completion menu that appears above the cursor.

### State Machine

The UI operates as a state machine. The status bar visually reflects the current state:

| State | Description | Status Bar Indicator | Key Bindings Active |
|-------|-------------|---------------------|---------------------|
| `INPUT` | Waiting for user input | (session info only) + `[🔨 Build]` or `[📋 Plan]` | Enter → submit, Tab → complete |
| `RUNNING` | AI is responding / executing tools | `[🔄 AI running...]` | None (input disabled) |
| `AWAITING_PERMISSION` | Tool needs user approval | `[❓ Confirm (y/n)]` | y / n / a |
| `AWAITING_QUESTION` | AI asked a question | `[❓ Answer above]` | Enter → submit answer |

Transitions:

```
INPUT ──(user submits message)──→ RUNNING
RUNNING ──(tool needs confirm)──→ AWAITING_PERMISSION
RUNNING ──(AI asks question)──→ AWAITING_QUESTION
AWAITING_PERMISSION ──(y/n/a)──→ RUNNING
AWAITING_QUESTION ──(Enter)──→ RUNNING
RUNNING ──(AI finishes)──→ INPUT
```

### Component Details

#### Output Buffer (`self.output_buffer`)

- A `Buffer` in read-only mode (`read_only=True`)
- Not focusable (prevents stealing focus from input buffer)
- Content is appended via `_append_output(text)` which uses `set_document(Document(...), bypass_readonly=True)`
- Callbacks like `_on_text_delta` append AI streaming text in real-time
- Scrollable to view conversation history

#### Input Buffer (`self.input_buffer`)

- A `Buffer` with `complete_while_typing=True` for auto-completion of `/commands`
- Uses `SlashCompleter` that provides completions for:
  - All slash commands (`/help`, `/clear`, `/tokens`, `/vscode`, `/session`, `/sessions`, `/exit`)
  - `/session new`, `/session delete`, `/session <n>`
  - Lists numbered sessions for auto-complete
- Completion menu rendered as a floating window via `FloatContainer` + `CompletionsMenu`
- Enter key behavior depends on current state (see state machine)

#### Status Bar (`_format_status()`)

- A `FormattedTextControl` that returns an `HTML` object
- Called by prompt_toolkit on each UI refresh
- Dynamically reads `self.session.title`, `self.cwd`, `self.agent.mode`, and `self._state`
- Shows session title, CWD (truncated to 50 chars), mode tag (`[🔨 Build]` / `[📋 Plan]`), and state indicator

#### Turn Separator

Each conversation turn (after the first) is separated by a `───` horizontal rule line, providing visual distinction between conversation rounds.

## File Layout

```
src/nano_claude/
├── interfaces/
│   ├── cli/
│   │   ├── cli.py  ← CLI entrypoint (click), session helpers, main()
│   │   └── ui.py   ← InteractiveUI class, SlashCompleter, _STYLE, _COMMANDS
│   └── web/
│       ├── app.py       ← FastAPI app factory + Uvicorn startup
│       ├── state.py     ← WebAppState (shared in-memory state)
│       ├── routers/     ← FastAPI routers (pages, system, sessions, setup, chat)
│       └── services/    ← Business logic (chat_service, setup_service, plan_service)
├── infra/
│   └── session.py  ← Session class + utility functions (session_path, list_sessions, etc.)
├── core/
│   └── agent.py    ← Core Agent class
└── ...
```

Key dependencies:
- `interfaces/cli/cli.py` imports `InteractiveUI` from `interfaces/cli/ui.py`
- `interfaces/cli/ui.py` imports session helpers (`list_sessions`, `save_current`, `session_info`, `session_path`) from `infra/session.py`
- `infra/session.py` provides shared utility functions used by both modules

## Integration with Agent

### Callback Override Mechanism

When the user submits a message (not a `/command`), `_handle_submit()` temporarily overrides the agent's callbacks:

```python
# Save originals
original_on_text_delta = self.agent.on_text_delta
...

# Override with UI-aware versions
self.agent.on_text_delta = self._on_text_delta      # → appends to output buffer
self.agent.on_tool_end = self._on_tool_end           # → appends "[title]" marker
self.agent.permission_callback = self._permission_callback  # → uses Future + keybindings
self.agent.ask_user_callback = self._ask_user_callback      # → uses Future + input area

# Run agent (await suspends this coroutine, event loop remains alive)
await self.agent.run_stream(text, self.cwd, session=self.session)

# Restore originals in finally block
```

This design means:
- The agent's streaming text goes directly into the UI output buffer
- Tool execution markers (`[bash]`, `[write]`, etc.) appear in the output area
- Permission requests and questions are handled within the UI, not via stdin

### Asynchronous Architecture

The entire system runs on a single asyncio event loop:

1. `Application.run()` starts the event loop and renders the UI
2. Key bindings schedule async tasks via `asyncio.ensure_future()`
3. `_handle_submit()` is a coroutine that `await`s `agent.run_stream()`
4. During `await`, the event loop continues processing UI events (key presses, UI refreshes)
5. `_permission_callback` and `_ask_user_callback` use `asyncio.Future` to suspend agent execution until user responds via key bindings

```
Event Loop Timeline:
├── Render UI
├── Key press (Enter) → ensure_future(_handle_submit)
├── _handle_submit runs:
│   ├── _append_output(separator)  # for turn > 0
│   ├── _append_output("> user message")
│   ├── await agent.run_stream(...)
│   │   ├── _on_text_delta("Hello") → _append_output + invalidate()
│   │   ├── _permission_callback() → create Future → await Future
│   │   │   └── (event loop: handle key 'y' → set Future result)
│   │   └── continue...
│   └── state = INPUT, turn_count += 1
├── Render UI (input re-enabled)
└── ... next iteration
```

## Permission Request Flow

When a tool (e.g. `bash`) requires user permission:

1. Agent calls `_permission_callback(tool, target, reason)`
2. UI shows the prompt in output area: `[!] Dangerous command: ...`
3. State transitions to `AWAITING_PERMISSION`
4. Creates an `asyncio.Future` and `await`s it (suspends agent)
5. Status bar shows `[❓ Confirm (y/n)]`
6. Key bindings handle `y`, `n`, `a`:
   - `y` → Future set to `"allow"`
   - `n` → Future set to `"deny"`
   - `a` → Future set to `"allow_always"`
7. Future resolves, agent resumes, state returns to `RUNNING`

## Question Flow

When the AI uses the `question` tool:

1. Agent calls `_ask_user_callback(header, question, options, multiple)`
2. UI shows the question and numbered options in output area
3. State transitions to `AWAITING_QUESTION`
4. Creates an `asyncio.Future` and `await`s it
5. Status bar shows `[❓ Answer above]`
6. User types answer in input area and presses Enter
7. `_handle_question_answer()` processes the response:
   - Looks up option by number or label
   - Supports comma-separated multiple selections
   - Supports "Custom" option (prompts for free-text input)
8. Future resolves, agent resumes

## Mode Switching

The status bar displays the current mode: `[🔨 Build]` or `[📋 Plan]`.

### Commands

| Command | Behavior |
|---------|----------|
| `/plan` | Calls `Agent.set_mode("plan")`, inserts transition message, shows confirmation |
| `/build` | Calls `Agent.set_mode("build")`, inserts transition message, shows confirmation |

Mode switching preserves the full conversation history — the agent sees the entire discussion across both modes.

### "执行" Workflow

When in plan mode, the UI has special handling for the `执行` (execute) trigger:

1. **After each plan mode response** (`_handle_submit` finally block):
   - Calls `_find_latest_plan()` to find the most recent `.md` file (excluding README.md, agents.md, etc.)
   - If found, appends the plan content to the output with a prompt: `输入「执行」切换到 build mode`

2. **When user types `执行`** (`_handle_submit` entry):
   - Finds the latest plan file via `_find_latest_plan()`
   - Calls `Agent.set_mode("build")`
   - Reads the plan file content
   - Injects it as context: user message with `"请按照以下计划严格执行：\n\n{plan_content}"`
   - Agent then runs in build mode and implements according to the plan

```python
def _find_latest_plan(self) -> str | None:
    md_files = list(Path(self.cwd).glob("*.md"))
    exclude = {"README.md", "LICENSE.md", "CHANGELOG.md",
               "CONTRIBUTING.md", "agents.md"}
    md_files = [f for f in md_files if f.name not in exclude]
    if not md_files:
        return None
    return str(max(md_files, key=os.path.getmtime))
```

## /commands in UI Mode

All slash commands are handled within the UI:

| Command | UI Behavior |
|---------|-------------|
| `/help` | Prints help text to output area |
| `/clear` | Resets output buffer and session messages |
| `/tokens` | Shows token count in output area |
| `/vscode` | Opens VS Code (output shown in UI) |
| `/session` | Shows session info in output area |
| `/session new` | Clears output, starts fresh session |
| `/session <n>` | Loads saved session, resets output |
| `/session delete <n\|all>` | Confirms via permission Future, deletes |
| `/sessions` | Lists sessions as plain text in output area |
| `/plan` | Switch to plan mode |
| `/build` | Switch to build mode |
| `/exit` | Calls `application.exit()` |

Note: `/sessions` and session management commands output **plain text** to the UI buffer rather than using Rich tables, since Rich's `console.print` would conflict with the full-screen TUI rendering.

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| `BufferControl(focusable=False)` on output | Prevents output window from stealing focus from input |
| `set_document(bypass_readonly=True)` for writes | Allows programmatic appends to read-only output buffer |
| `FloatContainer` + `CompletionsMenu` | Renders slash command completions as floating popup |
| `complete_while_typing=True` | Auto-completion triggers as user types (not just Tab) |
| `Condition()` wrappers for state filters | prompt_toolkit's `filter` parameter requires `Filter` instances |
| Turn counter + `───` separator | Visual distinction between conversation rounds |

## Key Differences from Old PromptSession Approach

| Aspect | Old (PromptSession) | New (Application) |
|--------|--------------------|--------------------|
| UI lifetime | Only during `prompt()` | Entire application lifetime |
| Footer visibility | Disappears during AI response | **Always visible** |
| Output method | Rich `console.print` | UI buffer append + `invalidate()` |
| Permission handling | `sys.stdin.readline` | `asyncio.Future` + key bindings |
| Question handling | `sys.stdin.readline` | Input buffer + `asyncio.Future` |
| Screen mode | Inline terminal | Full-screen (alternate buffer) |
| Completion style | Inline (PromptSession default) | FloatContainer popup menu |
| AI running indicator | None | Status bar shows `[🔄 AI running...]` |
| Turn separation | None | `───` separator between turns |
| Error resilience | Uncaught exceptions crash | Errors caught and shown in UI |
