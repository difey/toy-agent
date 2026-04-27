import os

from nano_claude.tool import Tool, ToolContext, ToolExecResult, check_file_permission


class WriteTool(Tool):
    @property
    def name(self) -> str:
        return "write"

    @property
    def description(self) -> str:
        return (
            "Write content to a file, overwriting if it exists. "
            "Creates parent directories if they don't exist. "
            "Use this to create new files or completely rewrite existing ones."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "filePath": {
                    "type": "string",
                    "description": "Absolute path to the file to write",
                },
                "content": {
                    "type": "string",
                    "description": "The content to write to the file",
                },
            },
            "required": ["filePath", "content"],
        }

    async def execute(self, args: dict, ctx: ToolContext) -> ToolExecResult:
        file_path = args["filePath"]
        content = args["content"]

        allowed, _ = await check_file_permission(ctx, file_path)
        if not allowed:
            return ToolExecResult(
                output=f"Permission denied: {file_path}",
                title="write [denied]",
            )

        parent = os.path.dirname(file_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            return ToolExecResult(
                output=f"Error writing file '{file_path}': {e}",
                title="write [error]",
            )

        fname = os.path.basename(file_path)
        return ToolExecResult(
            output=f"Wrote {len(content)} bytes to {file_path}",
            title=f"write [{fname}]",
        )
