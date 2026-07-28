"""Agent bootstrap — shared factory for building Agent instances."""

import os

from nano_claude.core.agent import Agent
from nano_claude.core.tool_registry import ToolRegistry
from nano_claude.infra.config import resolve_config
from nano_claude.infra.setup import load_user_config
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


def build_agent(cwd: str, mode: str = "build") -> Agent:
    """Build an Agent with tools, skills, and config for the given cwd.

    Args:
        cwd: Working directory, used to discover project-level SKILL.md.
        mode: "build" or "plan" (default "build").

    Returns:
        A fully configured Agent instance.
    """
    config = resolve_config()

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

    skill_store = SkillStore()
    skill_store.discover([
        cwd,
        os.path.expanduser("~/.nano_claude/skills"),
    ])

    agent = Agent(
        model=config.default_model,
        tools=registry,
        skill_store=skill_store,
        api_key=config.api_key,
        base_url=config.base_url,
        mode=mode,
    )
    # Restore the active provider name from config.toml
    user_cfg = load_user_config()
    if user_cfg:
        agent.provider = user_cfg.get("provider")

    return agent
