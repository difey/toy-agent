"""内建工具。"""

from mira.core.tools.builtin.file_tools import FileEditTool, FileReadTool, FileWriteTool
from mira.core.tools.builtin.search import GrepTool
from mira.core.tools.builtin.shell import ShellTool

BUILTIN_TOOLS = [
    ShellTool(),
    FileReadTool(),
    FileWriteTool(),
    FileEditTool(),
    GrepTool(),
]

__all__ = [
    "BUILTIN_TOOLS",
    "FileEditTool",
    "FileReadTool",
    "FileWriteTool",
    "GrepTool",
    "ShellTool",
]
