import asyncio
import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from nano_claude.agent import Agent
from nano_claude.config import resolve_config
from nano_claude.session import Session, list_sessions, save_current, session_info, session_path
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
from nano_claude.ui import InteractiveUI

console = Console()


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


def _ensure_cwd(cwd: str) -> str:
    resolved = str(Path(cwd).resolve())
    os.makedirs(resolved, exist_ok=True)
    return resolved


def _print_sessions(cwd: str) -> None:
    files = list_sessions(cwd)
    if not files:
        console.print("[dim]No saved sessions.[/dim]")
        return

    table = Table(title=f"Sessions in {cwd}/.session/")
    table.add_column("#", style="dim", width=4)
    table.add_column("Title")
    table.add_column("Msgs", width=5)
    table.add_column("Preview")
    for i, f in enumerate(files, 1):
        info = session_info(f)
        table.add_row(
            str(i),
            info["title"],
            str(info["messages"]),
            info["preview"],
        )
    console.print(table)


def _switch_session(
    session: Session, cwd: str, index: int, session_file_ref: list
) -> None:
    files = list_sessions(cwd)
    if index < 1 or index > len(files):
        console.print(f"[dim]Invalid session number: {index}[/dim]")
        return

    target = files[index - 1]
    if os.path.abspath(target) == os.path.abspath(session_file_ref[0]):
        console.print("[dim]Already on this session.[/dim]")
        return

    save_current(session, session_file_ref[0])

    try:
        new_session = Session.load(target)
    except Exception:
        console.print(f"[bold red]Failed to load session: {target}[/bold red]")
        return

    session.messages.clear()
    session.messages.extend(new_session.messages)
    session.title = new_session.title
    session_file_ref[0] = target

    info = session_info(target)
    console.print(f"[dim]Switched to session: {info['title']}  "
                  f"Messages: {info['messages']}[/dim]")


def _delete_session(
    session: Session, cwd: str, target: str, session_file_ref: list
) -> None:
    files = list_sessions(cwd)
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
        console.print(f"[dim]Usage: /sessions delete <n> or /sessions delete all[/dim]")
        return

    index = int(target)
    if index < 1 or index > len(files):
        console.print(f"[dim]Invalid session number: {index}[/dim]")
        return

    target_file = files[index - 1]
    target_abs = os.path.abspath(target_file)

    if target_abs == os.path.abspath(session_file_ref[0]):
        console.print("[dim]Cannot delete the current active session. Switch to another session first.[/dim]")
        return

    try:
        os.remove(target_file)
        info = session_info(target_file)
        console.print(f"[dim]Deleted session {index}: {info['name']} ({info['messages']} messages)[/dim]")
    except OSError as e:
        console.print(f"[bold red]Failed to delete session: {e}[/bold red]")


def _run_interactive(agent: Agent, cwd: str, session: Session, session_file_ref: list) -> None:
    """Run interactive mode with persistent TUI and always-visible bottom toolbar."""
    ui = InteractiveUI(agent, cwd, session, session_file_ref)
    ui.run()


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
        permission_callback=None,  # Will be overridden in interactive mode
        ask_user_callback=None,     # Will be overridden in interactive mode
        on_text_delta=None,         # Will be overridden in interactive mode
        on_tool_start=None,
        on_tool_end=None,           # Will be overridden in interactive mode
    )

    session = Session()
    session_file = session_path(resolved_cwd)
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


if __name__ == "__main__":
    main()
