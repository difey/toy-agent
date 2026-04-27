import os

from nano_claude.tool import (
    Tool,
    ToolContext,
    ToolExecResult,
    check_file_permission,
    resolve_safe_path,
)


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
                    "description": "Path to the file to write. Can be relative to cwd or absolute.",
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

        # Resolve path with hallucination correction
        resolved_path = resolve_safe_path(file_path, ctx)

        allowed, _ = await check_file_permission(ctx, resolved_path)
        if not allowed:
            return ToolExecResult(
                output=f"Permission denied: {resolved_path}",
                title="write [denied]",
            )

        hint = ""
        if file_path != resolved_path:
            hint = (
                f"\nNote: Path '{file_path}' was auto-corrected to '{resolved_path}' "
                f"(cwd is '{ctx.cwd}')."
            )

        parent = os.path.dirname(resolved_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        try:
            with open(resolved_path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            return ToolExecResult(
                output=f"Error writing file '{resolved_path}': {e}",
                title="write [error]",
            )

        fname = os.path.basename(resolved_path)
        return ToolExecResult(
            output=f"Wrote {len(content)} bytes to {resolved_path}{hint}",
            title=f"write [{fname}]",
        )
