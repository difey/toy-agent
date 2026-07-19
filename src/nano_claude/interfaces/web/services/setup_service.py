"""Setup wizard service — persists user config and (re)builds the core Agent."""

import os

from nano_claude.core.agent import Agent
from nano_claude.core.tool_registry import ToolRegistry
from nano_claude.infra.setup import has_user_config, load_user_config, save_user_config
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

from nano_claude.interfaces.web.state import WebAppState


def needs_setup() -> bool:
    """Check if the user has a saved config file (~/.nano_claude/config.toml)."""
    return not has_user_config()


def setup_status() -> dict:
    """Check if the user has saved config (~/.nano_claude/config.toml)."""
    configured = has_user_config()
    model = None
    if configured:
        cfg = load_user_config()
        if cfg:
            model = cfg.get("model")
    return {
        "configured": configured,
        "model": model,
    }


def _build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for tool_cls in (BashTool, ReadTool, WriteTool, EditTool, GlobTool, GrepTool,
                     WebFetchTool, WebSearchTool, CodeSearchTool, DelegateTool,
                     TodoWriteTool, QuestionTool, ApplyPatchTool, SkillTool):
        registry.register(tool_cls())
    return registry


def apply_setup(state: WebAppState, model: str, api_key: str) -> None:
    """Save user configuration and create or update the shared core Agent."""
    from nano_claude.infra.config import resolve_config

    save_user_config(model, api_key)

    cfg = resolve_config(model)

    if state.agent is None:
        # Create a brand new agent
        registry = _build_registry()
        skill_store = SkillStore()
        skill_store.discover([
            state.cwd,
            os.path.expanduser("~/.nano_claude/skills"),
        ])

        state.agent = Agent(
            model=model,
            tools=registry,
            skill_store=skill_store,
            api_key=cfg.api_key,
            base_url=cfg.base_url,
        )
        # Re-initialize the session
        state.session.messages.clear()
        state.session.title = ""
    else:
        # Update existing agent
        state.agent.model = model
        if cfg.api_key:
            state.agent.api_key = cfg.api_key
        if cfg.base_url:
            state.agent.base_url = cfg.base_url
        state.agent._client = None  # Force re-create LLM client


def resolve_api_key(api_key: str | None) -> str | None:
    """Fall back to well-known environment variables when no API key is provided."""
    if api_key:
        return api_key
    for env_var in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "NANO_CLAUDE_API_KEY"):
        val = os.environ.get(env_var)
        if val:
            return val
    return None
