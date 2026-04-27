import inspect
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

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


def _resolve_path(path: str, cwd: str) -> str:
    p = os.path.join(cwd, path) if not os.path.isabs(path) else path
    return os.path.realpath(p)


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
    resolved_path = _resolve_path(file_path, ctx.cwd)

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

    def get_tools_prompt(self, **kwargs) -> str:
        lines = ["## Available Tools"]
        lines.append(f"You have the following tools: {', '.join(self._tools)}.")
        for tool in self._tools.values():
            text = tool.prompt_text.format(**kwargs) if kwargs else tool.prompt_text
            lines.append(f"- {text}")
        return "\n".join(lines)
