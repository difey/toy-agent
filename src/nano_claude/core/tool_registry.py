"""Tool base class and registry used to expose tools to the LLM."""

import inspect
import os
from abc import ABC, abstractmethod

from nano_claude.core.tool_contracts import ToolContext, ToolExecResult


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
