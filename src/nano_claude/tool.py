import inspect
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    from nano_claude.agent import Agent

# PermissionCallback: returns "allow" | "deny" | "allow_always"
PermissionCallback = Callable[[str, str, str], Awaitable[str]]


@dataclass
class ToolExecResult:
    output: str
    title: str = ""
    metadata: dict = field(default_factory=dict)


AskUserCallback = Callable[[str, str, list[dict], bool], Awaitable[list[str]]]


@dataclass
class ToolContext:
    cwd: str
    allowed_files: set = field(default_factory=set)
    permission_callback: PermissionCallback | None = None
    ask_user_callback: AskUserCallback | None = None
    mode: str = "build"  # "plan" or "build"
    parent_agent: Any | None = None  # Reference to parent Agent (for delegate tool)
    on_event: Callable[[str, dict], Awaitable[None]] | None = None  # Real-time event pusher (for sub-agent streaming)
    skill_store: Any | None = None  # SkillStore instance for the skill tool


# Common hallucinated base paths that LLMs tend to generate instead of the real cwd.
# These are paths commonly seen in training data (CodinGame, LeetCode, cloud IDEs, etc.).
HALLUCINATED_BASE_PATHS = [
    "/workspace",
    "/project",
    "/app",
    "/code",
    "/home/user",
    "/home/project",
    "/home/developer",
    "/root",
    "/src",
    "/source",
    "/Users/user",
    "/home/coder",
    "/sandbox",
]

# How many path components to strip when a hallucinated base is detected.
# E.g. /workspace/src/foo/bar.py with cwd=/real/path → /real/path/src/foo/bar.py
# If the hallucinated path has extra prefix components, we strip them.
_HALLUCINATION_STRIP_PREFIXES = ["src/", "source/", "app/", "code/"]


def _resolve_path(path: str, cwd: str) -> str:
    p = os.path.join(cwd, path) if not os.path.isabs(path) else path
    return os.path.realpath(p)


def correct_hallucinated_path(path: str, cwd: str) -> str:
    """Detect and correct paths that look like LLM hallucinations.

    The LLM sometimes generates paths like `/workspace/src/foo/bar.py` even
    though the actual project root is something completely different (e.g.
    `/Users/name/real-project/`). This function detects such cases and
    remaps the path to the real cwd.

    Returns the corrected path if a hallucination was detected and fixed,
    or the original path otherwise.
    """
    if not os.path.isabs(path):
        return path  # Relative paths are fine

    resolved_cwd = os.path.realpath(cwd)

    # If the path already exists and is within cwd, no correction needed
    try:
        if os.path.exists(path):
            resolved = os.path.realpath(path)
            if _is_within_cwd(resolved, resolved_cwd):
                return path  # Already correct
    except (OSError, ValueError):
        pass

    corrected = path

    # Check if the path starts with a known hallucinated base
    for base in HALLUCINATED_BASE_PATHS:
        if path.startswith(base + "/") or path == base:
            rel_part = path[len(base):].lstrip("/")
            corrected = os.path.join(resolved_cwd, rel_part)
            break

    # Also check for paths that look like they dropped the project root entirely
    # e.g. "/src/nano_claude/cli.py" instead of "/real/cwd/src/nano_claude/cli.py"
    if corrected == path:
        for prefix in _HALLUCINATION_STRIP_PREFIXES:
            check_path = "/" + prefix.rstrip("/")
            if path.startswith(check_path):
                rel_part = path[len(check_path):].lstrip("/")
                corrected = os.path.join(resolved_cwd, prefix.rstrip("/"), rel_part)
                break

    return corrected


def resolve_safe_path(path: str, ctx: ToolContext) -> str:
    """Resolve a file path with hallucination correction.

    Steps:
    1. If relative, join with ctx.cwd
    2. Apply hallucination correction (remap /workspace/... → ctx.cwd/...)
    3. Resolve to real path

    Returns the resolved absolute path.
    """
    # Step 1: Make absolute if relative
    if not os.path.isabs(path):
        path = os.path.join(ctx.cwd, path)

    # Step 2: Correct hallucinated bases
    corrected = correct_hallucinated_path(path, ctx.cwd)

    # Step 3: Resolve to real path
    try:
        return os.path.realpath(corrected)
    except OSError:
        return corrected


def _is_within_cwd(path: str, cwd: str) -> bool:
    try:
        resolved_path = os.path.realpath(path)
        resolved_cwd = os.path.realpath(cwd)
        common = os.path.commonpath([resolved_path, resolved_cwd])
        return common == resolved_cwd
    except (ValueError, OSError):
        return False


async def check_file_permission(
    ctx: ToolContext, file_path: str
) -> tuple[bool, str]:
    resolved_cwd = os.path.realpath(ctx.cwd)
    resolved_path = resolve_safe_path(file_path, ctx)

    if _is_within_cwd(resolved_path, resolved_cwd):
        return True, ""

    if resolved_path in ctx.allowed_files:
        return True, ""

    if ctx.permission_callback is None:
        return True, ""

    result = await ctx.permission_callback("file", file_path, resolved_path)
    if result == "allow_always":
        ctx.allowed_files.add(resolved_path)
        return True, ""
    return result == "allow", result


def _find_prompt_file(cls: type) -> str | None:
    try:
        src = inspect.getfile(cls)
    except TypeError:
        return None
    base, _ = os.path.splitext(src)
    txt = base + ".txt"
    if os.path.exists(txt):
        return txt
    return None


class Tool(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def parameters(self) -> dict: ...

    @property
    def prompt_text(self) -> str:
        path = _find_prompt_file(type(self))
        if path:
            with open(path, "r") as f:
                return f.read().strip()
        return self.description

    @abstractmethod
    async def execute(self, args: dict, ctx: ToolContext) -> ToolExecResult: ...


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def to_openai_tools(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    def filtered_copy(self, names: set[str]) -> "ToolRegistry":
        """Return a new ToolRegistry with only the specified tool names."""
        new_registry = ToolRegistry()
        for name in names:
            if name in self._tools:
                new_registry.register(self._tools[name])
        return new_registry

    def get_tools_prompt(self, **kwargs) -> str:
        lines = ["## Available Tools"]
        lines.append(f"You have the following tools: {', '.join(self._tools)}.")
        for tool in self._tools.values():
            text = tool.prompt_text.format(**kwargs) if kwargs else tool.prompt_text
            lines.append(f"- {text}")
        return "\n".join(lines)
