import asyncio
import glob
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import click
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.table import Table
from rich.text import Text

from nano_claude.agent import Agent
from nano_claude.config import resolve_config
from nano_claude.message import ToolCall
from nano_claude.session import Session
from nano_claude.setup import has_user_config, run_wizard
from nano_claude.tool import ToolRegistry
from nano_claude.tools import (
    ApplyPatchTool,
    BashTool,
    CodeSearchTool,
    EditTool,
    GlobTool,
    GrepTool,
    QuestionTool,
    ReadTool,
    TodoWriteTool,
    WebFetchTool,
    WebSearchTool,
    WriteTool,
)

console = Console()

_STYLE = Style.from_dict({
    "prompt": "bold",
})

_COMMANDS = [
    "/help",
    "/clear",
    "/tokens",
    "/vscode",
    "/session",
    "/sessions",
    "/exit",
]


class SlashCompleter(Completer):
    def __init__(self, cwd: str):
        self.cwd = cwd

    def get_completions(self, document, complete_event):
        word = document.text_before_cursor
        for cmd in _COMMANDS:
            if cmd.startswith(word):
                yield Completion(cmd, start_position=-len(word))
        if word.startswith("/session "):
            yield Completion("/session new", start_position=-len(word))
            yield Completion("/session delete ", start_position=-len(word))
            for i, _ in enumerate(_list_sessions(self.cwd), 1):
                yield Completion(f"/session {i}", start_position=-len(word))
        if word.startswith("/session delete "):
            yield Completion("/session delete all", start_position=-len(word))
            for i, _ in enumerate(_list_sessions(self.cwd), 1):
                yield Completion(f"/session delete {i}", start_position=-len(word))


def _build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(BashTool())
    registry.register(ReadTool())
    registry.register(WriteTool())
    registry.register(EditTool())
    registry.register(GlobTool())
    registry.register(GrepTool())
    registry.register(WebFetchTool())
    registry.register(WebSearchTool())
    registry.register(CodeSearchTool())
    registry.register(TodoWriteTool())
    registry.register(QuestionTool())
    registry.register(ApplyPatchTool())
    return registry


def _on_text_delta(text: str):
    console.print(text, end="")


def _on_tool_start(call: ToolCall):
    pass


def _on_tool_end(name: str, title: str, output: str):
    style = "dim"
    if "error" in title.lower() or "blocked" in title.lower():
        style = "bold red"
    elif "timeout" in title.lower():
        style = "bold yellow"
    elif "denied" in title.lower():
        style = "bold yellow"

    label = Text(f"\n  [{title}]", style=style)
    console.print(label)


async def _permission_callback(tool: str, target: str, reason: str) -> str:
    console.print()
    if tool == "bash":
        console.print(f"  [!] [bold yellow]Dangerous command detected:[/bold yellow] {reason}")
        console.print(f"  Command: {target[:100]}")
        console.print("  [dim]\\[y]es / \\[n]o[/dim]", end="")
    else:
        console.print(f"  [!] [bold yellow]{tool} wants to access:[/bold yellow] {target}")
        console.print("  [dim]\\[y]es / \\[n]o / \\[a]lways allow this file[/dim]", end="")

    console.print(" ", end="")
    sys.stdout.flush()

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, sys.stdin.readline)
        choice = result.strip().lower()
    except Exception:
        choice = "n"

    if choice in ("y", "yes"):
        return "allow"
    if choice in ("a", "always"):
        return "allow_always"
    return "deny"


async def _ask_user_callback(
    header: str, question: str, options: list[dict], multiple: bool
) -> list[str]:
    """Display a question to the user and return their answer(s)."""
    console.print()
    console.print(f"  [bold cyan]{header}[/bold cyan]")
    console.print(f"  {question}")
    console.print()

    option_map: dict[str, str] = {}
    for i, opt in enumerate(options, 1):
        label = opt["label"]
        desc = opt.get("description", "")
        option_map[str(i)] = label
        option_map[label.lower()] = label
        desc_text = f" - {desc}" if desc else ""
        console.print(f"    {i}. [bold]{label}[/bold]{desc_text}")

    custom_idx = len(options) + 1
    console.print(f"    {custom_idx}. [bold]Custom[/bold] (type your own answer)")
    console.print()

    answers: list[str] = []
    prompt_text = f"  Your answer (1-{custom_idx}{', comma-separated for multiple' if multiple else ''}): "
    console.print(prompt_text, end="")
    sys.stdout.flush()

    try:
        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(None, sys.stdin.readline)
    except Exception:
        return []

    raw = raw.strip()
    if not raw:
        return []

    selected = [s.strip() for s in raw.replace("，", ",").split(",") if s.strip()]

    for choice in selected:
        if choice in option_map:
            answers.append(option_map[choice])
        elif choice.isdigit() and int(choice) == custom_idx:
            console.print("  Type your answer: ", end="")
            sys.stdout.flush()
            try:
                custom = await loop.run_in_executor(None, sys.stdin.readline)
                answers.append(custom.strip() or "(skipped)")
            except Exception:
                answers.append("(skipped)")
        elif choice.isdigit() and 1 <= int(choice) <= len(options):
            answers.append(options[int(choice) - 1]["label"])
        else:
            answers.append(choice)

    if not answers:
        return ["(skipped)"]

    return answers


def _session_path(cwd: str) -> str:
    ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    directory = os.path.join(cwd, ".session")
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, f"{ts}.json")


def _ensure_cwd(cwd: str) -> str:
    resolved = str(Path(cwd).resolve())
    os.makedirs(resolved, exist_ok=True)
    return resolved


@click.command()
@click.argument("message", required=False)
@click.option("--model", default=None, help="LLM model (auto-detects provider from model name)")
@click.option("--cwd", default=None, help="Working directory (default: current directory)")
@click.option("--setup", "force_setup", is_flag=True, default=False, help="Re-run the setup wizard")
def main(message: str | None, model: str | None, cwd: str | None, force_setup: bool):
    """nanoClaude - a CLI coding assistant that uses tools to complete coding tasks.

    Set DEEPSEEK_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY, or NANO_CLAUDE_API_KEY
    depending on the provider. Provider is auto-detected from the model name:

    \b
      deepseek-v4-pro     → DeepSeek (needs DEEPSEEK_API_KEY)
      deepseek-v4-flash    → DeepSeek (needs DEEPSEEK_API_KEY)
      gpt-4o, gpt-4.1      → OpenAI (needs OPENAI_API_KEY)
      claude-*             → Anthropic (needs ANTHROPIC_API_KEY)

    Run without MESSAGE to enter interactive multi-turn mode.

    Session files are auto-saved to <cwd>/.session/<timestamp>.json.
    Configuration is stored at ~/.nano_claude/config.toml.
    """

    if force_setup or not has_user_config():
        run_wizard(console)

    config = resolve_config(model)
    if not config.api_key:
        console.print(f"[bold red]Error:[/bold red] No API key found for provider '{config.name}'.")
        console.print(f"  Set {config.name.upper()}_API_KEY or NANO_CLAUDE_API_KEY environment variable,")
        console.print(f"  or run `nano-claude --setup` to configure.")
        sys.exit(1)

    resolved_model = config.default_model
    resolved_cwd = _ensure_cwd(cwd or os.getcwd())

    registry = _build_registry()
    agent = Agent(
        model=resolved_model,
        tools=registry,
        api_key=config.api_key,
        base_url=config.base_url,
        permission_callback=_permission_callback,
        ask_user_callback=_ask_user_callback,
        on_text_delta=_on_text_delta,
        on_tool_start=_on_tool_start,
        on_tool_end=_on_tool_end,
    )

    session = Session()
    session_file = _session_path(resolved_cwd)
    session_file_ref = [session_file]

    try:
        if message:
            asyncio.run(agent.run_stream(message, resolved_cwd, session=session))
            console.print()
        else:
            _run_interactive(agent, resolved_cwd, session, session_file_ref)
    except (KeyboardInterrupt, EOFError):
        console.print()
    except Exception as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        sys.exit(1)
    finally:
        session.save(session_file_ref[0])


def _list_sessions(cwd: str) -> list[str]:
    pattern = os.path.join(cwd, ".session", "*.json")
    return sorted(glob.glob(pattern))


def _session_info(filepath: str) -> dict:
    try:
        sess = Session.load(filepath)
        first_msg = ""
        for m in sess.messages:
            from nano_claude.message import UserMessage
            if isinstance(m, UserMessage) and isinstance(m.content, str):
                first_msg = m.content
                break
        return {
            "path": filepath,
            "name": os.path.splitext(os.path.basename(filepath))[0],
            "messages": len(sess.messages),
            "tokens": sess.total_tokens(),
            "preview": first_msg[:60] + ("..." if len(first_msg) > 60 else ""),
        }
    except Exception:
        return {
            "path": filepath,
            "name": os.path.basename(filepath),
            "messages": 0,
            "tokens": 0,
            "preview": "(unreadable)",
        }


def _print_sessions(cwd: str) -> None:
    files = _list_sessions(cwd)
    if not files:
        console.print("[dim]No saved sessions.[/dim]")
        return

    table = Table(title=f"Sessions in {cwd}/.session/")
    table.add_column("#", style="dim", width=4)
    table.add_column("Timestamp")
    table.add_column("Msgs", width=5)
    table.add_column("Tokens", width=7)
    table.add_column("First message")
    for i, f in enumerate(files, 1):
        info = _session_info(f)
        table.add_row(
            str(i),
            info["name"],
            str(info["messages"]),
            str(info["tokens"]),
            info["preview"],
        )
    console.print(table)


def _run_interactive(agent: Agent, cwd: str, session: Session, session_file_ref: list) -> None:
    prompt_session = PromptSession(
        completer=SlashCompleter(cwd),
        style=_STYLE,
    )
    console.print("[dim]nanoClaude interactive mode. Type /help for commands, Tab to complete, Ctrl+C to exit.[/dim]")

    while True:
        try:
            line = prompt_session.prompt([("class:prompt", "> ")])
        except (KeyboardInterrupt, EOFError):
            break

        line = line.strip()
        if not line:
            continue

        if _handle_command(line, agent, cwd, session, session_file_ref):
            continue

        try:
            asyncio.run(agent.run_stream(line, cwd, session=session))
        except (KeyboardInterrupt, EOFError):
            console.print()
            continue
        console.print()


def _handle_command(
    line: str, agent: Agent, cwd: str, session: Session, session_file_ref: list
) -> bool:
    parts = line.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == "/help":
        console.print("  /help                Show this help")
        console.print("  /clear               Clear conversation history")
        console.print("  /tokens              Show token usage")
        console.print("  /vscode              Open current working directory in VS Code")
        console.print("  /session             Show current session info")
        console.print("  /session new         Start a new session")
        console.print("  /sessions            List all saved sessions")
        console.print("  /session <n>         Switch to session n (from /sessions list)")
        console.print("  /session delete <n>  Delete session n")
        console.print("  /session delete all  Delete all saved sessions")
        console.print("  /exit                Exit")
        return True

    if cmd == "/exit":
        raise EOFError()

    if cmd == "/clear":
        session.messages.clear()
        console.print("[dim]Conversation cleared.[/dim]")
        return True

    if cmd == "/tokens":
        console.print(f"[dim]~{session.total_tokens()} tokens used.[/dim]")
        return True

    if cmd == "/vscode":
        try:
            subprocess.run(["code", cwd], check=True)
            console.print(f"[dim]Opened VS Code at {cwd}[/dim]")
        except FileNotFoundError:
            console.print("[bold red]Error:[/bold red] `code` command not found. Make sure VS Code is installed and the `code` CLI is in your PATH.")
        except subprocess.CalledProcessError as e:
            console.print(f"[bold red]Error:[/bold red] Failed to open VS Code: {e}")
        return True

    if cmd == "/sessions":
        _print_sessions(cwd)
        return True

    if cmd == "/session":
        if arg == "new":
            _save_current(session, session_file_ref[0])
            session.messages.clear()
            session_file_ref[0] = _session_path(cwd)
            console.print(f"[dim]New session started: {os.path.basename(session_file_ref[0])}[/dim]")
            return True
        if arg.startswith("delete "):
            _delete_session(session, cwd, arg[7:], session_file_ref)
            return True
        if arg.isdigit():
            _switch_session(session, cwd, int(arg), session_file_ref)
            return True
        info = _session_info(session_file_ref[0])
        console.print(f"[dim]Session: {info['name']}  "
                      f"Messages: {info['messages']}  "
                      f"Tokens: ~{info['tokens']}[/dim]")
        return True

    return False


def _save_current(session: Session, filepath: str) -> None:
    if session.messages:
        session.save(filepath)


def _switch_session(
    session: Session, cwd: str, index: int, session_file_ref: list
) -> None:
    files = _list_sessions(cwd)
    if index < 1 or index > len(files):
        console.print(f"[dim]Invalid session number: {index}[/dim]")
        return

    target = files[index - 1]
    if os.path.abspath(target) == os.path.abspath(session_file_ref[0]):
        console.print("[dim]Already on this session.[/dim]")
        return

    _save_current(session, session_file_ref[0])

    try:
        new_session = Session.load(target)
    except Exception:
        console.print(f"[bold red]Failed to load session: {target}[/bold red]")
        return

    session.messages.clear()
    session.messages.extend(new_session.messages)
    session_file_ref[0] = target

    info = _session_info(target)
    console.print(f"[dim]Switched to session: {info['name']}  "
                  f"Messages: {info['messages']}  "
                  f"Tokens: ~{info['tokens']}[/dim]")


def _delete_session(
    session: Session, cwd: str, target: str, session_file_ref: list
) -> None:
    files = _list_sessions(cwd)
    if not files:
        console.print("[dim]No saved sessions to delete.[/dim]")
        return

    if target == "all":
        console.print("[yellow]Delete ALL saved sessions? This cannot be undone.[/yellow]")
        console.print("  [dim]\\[y]es / \\[n]o[/dim] ", end="")
        sys.stdout.flush()
        try:
            choice = sys.stdin.readline().strip().lower()
        except Exception:
            choice = "n"
        if choice not in ("y", "yes"):
            console.print("[dim]Cancelled.[/dim]")
            return

        current_abs = os.path.abspath(session_file_ref[0])
        deleted_count = 0
        for f in files:
            if os.path.abspath(f) != current_abs:
                try:
                    os.remove(f)
                    deleted_count += 1
                except OSError:
                    pass
        if deleted_count:
            console.print(f"[dim]Deleted {deleted_count} session(s).[/dim]")
        else:
            console.print("[dim]No sessions to delete (only current session remains).[/dim]")
        return

    if not target.isdigit():
        console.print(f"[dim]Usage: /session delete <n> or /session delete all[/dim]")
        return

    index = int(target)
    if index < 1 or index > len(files):
        console.print(f"[dim]Invalid session number: {index}[/dim]")
        return

    target_file = files[index - 1]
    target_abs = os.path.abspath(target_file)

    # Check if deleting the current session
    if target_abs == os.path.abspath(session_file_ref[0]):
        console.print("[dim]Cannot delete the current active session. Switch to another session first.[/dim]")
        return

    try:
        os.remove(target_file)
        info = _session_info(target_file)
        console.print(f"[dim]Deleted session {index}: {info['name']} ({info['messages']} messages)[/dim]")
    except OSError as e:
        console.print(f"[bold red]Failed to delete session: {e}[/bold red]")


if __name__ == "__main__":
    main()
