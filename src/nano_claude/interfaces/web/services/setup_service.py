"""Setup helpers — API key resolution, kept for reference."""
import os


def resolve_api_key(api_key: str | None) -> str | None:
    """Fall back to well-known environment variables when no API key is provided."""
    if api_key:
        return api_key
    for env_var in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "NANO_CLAUDE_API_KEY"):
        val = os.environ.get(env_var)
        if val:
            return val
    return None
