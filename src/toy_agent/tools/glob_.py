import glob
import os

from toy_agent.tool import Tool, ToolContext, ToolExecResult


class GlobTool(Tool):
    @property
    def name(self) -> str:
        return "glob"

    @property
    def description(self) -> str:
        return (
            "Fast file pattern matching tool. "
            "Supports glob patterns like '**/*.py' or 'src/**/*.ts'. "
            "Returns matching file paths sorted by modification time."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "The glob pattern to match files against",
                },
                "path": {
                    "type": "string",
                    "description": "The directory to search in. Defaults to the working directory.",
                },
            },
            "required": ["pattern"],
        }

    async def execute(self, args: dict, ctx: ToolContext) -> ToolExecResult:
        pattern = args["pattern"]
        search_path = args.get("path", ctx.cwd)

        if not os.path.isdir(search_path):
            return ToolExecResult(
                output=f"Error: path not found: {search_path}",
                title="glob [error]",
            )

        full_pattern = os.path.join(search_path, pattern)
        matches = sorted(
            glob.glob(full_pattern, recursive=True),
            key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0,
            reverse=True,
        )

        if not matches:
            output = "(no matches)"
        else:
            output = "\n".join(matches[:200])
            if len(matches) > 200:
                output += f"\n... ({len(matches) - 200} more results)"

        return ToolExecResult(
            output=output,
            title=f"glob [{pattern}]",
            metadata={"count": len(matches)},
        )
