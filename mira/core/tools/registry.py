"""ToolRegistry：注册 / 查找 / 枚举 / 组装工具描述。"""

from __future__ import annotations

from mira.core.tools.base import Tool
from mira.core.tools.builtin.apply_patch import ApplyPatchTool
from mira.core.tools.builtin.attach_image import AttachImageTool
from mira.core.tools.builtin.file_tools import FileEditTool, FileReadTool, FileWriteTool
from mira.core.tools.builtin.glob_tool import GlobTool
from mira.core.tools.builtin.project_memory import ProjectMemoryTool
from mira.core.tools.builtin.search import GrepTool
from mira.core.tools.builtin.shell import ShellTool
from mira.core.tools.builtin.todowrite import TodoWriteTool
from mira.core.tools.builtin.webfetch import WebFetchTool
from mira.core.tools.builtin.websearch import WebSearchTool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> "ToolRegistry":
        self._tools[tool.name] = tool
        return self

    def register_many(self, tools: list[Tool]) -> "ToolRegistry":
        for tool in tools:
            self.register(tool)
        return self

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return sorted(self._tools)

    def enabled(self, names: list[str]) -> list[Tool]:
        """按 agent 配置过滤出已注册工具（跳过未注册的，交由运行时告警）。"""
        return [self._tools[n] for n in names if n in self._tools]

    def missing(self, names: list[str]) -> list[str]:
        return [n for n in names if n not in self._tools]

    @classmethod
    def with_builtins(cls) -> "ToolRegistry":
        """注册全部内建工具：shell / 文件 / 检索 / glob / todowrite / project_memory / apply_patch / web_fetch / web_search。"""
        return cls().register_many(
            [
                ShellTool(),
                FileReadTool(),
                FileWriteTool(),
                FileEditTool(),
                GrepTool(),
                GlobTool(),
                TodoWriteTool(),
                ProjectMemoryTool(),
                ApplyPatchTool(),
                WebFetchTool(),
                WebSearchTool(),
                AttachImageTool(),
            ]
        )
