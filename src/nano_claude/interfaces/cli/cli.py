import argparse
import asyncio
import os
import sys
from pathlib import Path

from nano_claude.core.agent import Agent
from nano_claude.core.tool_registry import ToolRegistry
from nano_claude.infra.config import resolve_config
from nano_claude.infra.session import Session, migrate_old_sessions, save_current
from nano_claude.infra.session_service import resume_or_create_session
from nano_claude.tools import (
    ApplyPatchTool,
    BashTool,
    CodeSearchTool,
    DelegateTool,
    EditTool,
    GlobTool,
    GrepTool,
    QuestionTool,
    ReadTool,
    SkillTool,
    TodoWriteTool,
    WebFetchTool,
    WebSearchTool,
    WriteTool,
)
from nano_claude.tools.skill import SkillStore


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
    registry.register(DelegateTool())
    registry.register(TodoWriteTool())
    registry.register(QuestionTool())
    registry.register(ApplyPatchTool())
    registry.register(SkillTool())
    return registry


def _ensure_cwd(cwd: str) -> str:
    resolved = str(Path(cwd).resolve())
    os.makedirs(resolved, exist_ok=True)
    return resolved


def _start_web(agent: Agent | None, cwd: str, session: Session, session_file: str, port: int) -> None:
    """Run the web UI server using FastAPI + Uvicorn."""
    from nano_claude.interfaces.web.app import start_web_ui

    try:
        start_web_ui(agent, cwd, session, session_file, port=port)
    except KeyboardInterrupt:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="nano-claude",
        description="nanoClaude - a CLI coding assistant with web UI.",
    )
    parser.add_argument("message", nargs="?", default=None,
                        help="Single-turn message (omit to start web UI server)")
    parser.add_argument("--model", default=None,
                        help="LLM model (auto-detects provider from model name)")
    parser.add_argument("--cwd", default=None,
                        help="Working directory (default: current directory)")
    parser.add_argument("--port", type=int, default=8080,
                        help="Port for web UI server (default: 8080)")
    parser.add_argument("--plan", action="store_true", default=False,
                        help="Start in plan mode (discuss requirements only)")

    args = parser.parse_args()

    config = resolve_config(args.model)
    if not config.api_key:
        print(f"Error: No API key found for provider '{config.name}'.")
        print(f"  Set {config.name.upper()}_API_KEY or NANO_CLAUDE_API_KEY environment variable.")
        sys.exit(1)

    resolved_model = config.default_model
    resolved_cwd = _ensure_cwd(args.cwd or os.getcwd())

    # Migrate old .session/ files to new home-directory storage
    migrated = migrate_old_sessions(resolved_cwd)
    if migrated:
        print(f"  📦 Migrated {migrated} session(s) from .session/ to ~/.nano_claude/sessions/")

    registry = _build_registry()

    # Discover domain-specific skills from SKILL.md files
    skill_store = SkillStore()
    skill_store.discover([
        resolved_cwd,
        os.path.expanduser("~/.nano_claude/skills"),
    ])
    if skill_store.count > 0:
        names = ", ".join(s.name for s in skill_store.list_all())
        print(f"  📚 Discovered {skill_store.count} skills: {names}")

    agent = Agent(
        model=resolved_model,
        tools=registry,
        skill_store=skill_store,
        api_key=config.api_key,
        base_url=config.base_url,
        mode="plan" if args.plan else "build",
    )

    # 启动时自动接续最近一次的 session，避免每次启动都产生新文件
    session, session_file = resume_or_create_session(resolved_cwd)

    try:
        if args.message:
            asyncio.run(agent.run_stream(args.message, resolved_cwd, session=session))
            print()
        else:
            _start_web(agent, resolved_cwd, session, session_file, args.port)
    except (KeyboardInterrupt, EOFError):
        print()
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)
    finally:
        save_current(session, session_file)


if __name__ == "__main__":
    main()
