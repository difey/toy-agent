import os

from nano_claude.tool import (
    Tool,
    ToolContext,
    ToolExecResult,
    check_file_permission,
    resolve_safe_path,
)


class ReadTool(Tool):
    @property
    def name(self) -> str:
        return "read"

    @property
    def description(self) -> str:
        return (
            "Read a file from the local filesystem. "
            "Returns contents with line numbers prefixed. "
            "Use `offset` and `limit` (especially handy for long files), "
            "but it's recommended to read the whole file by not providing these parameters."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "filePath": {
                    "type": "string",
                    "description": "Path to the file to read. Can be relative to cwd or absolute.",
                },
                "offset": {
                    "type": "number",
                    "description": "Line number to start reading from (1-indexed)",
                },
                "limit": {
                    "type": "number",
                    "description": "Maximum number of lines to read",
                },
            },
            "required": ["filePath"],
        }

    async def execute(self, args: dict, ctx: ToolContext) -> ToolExecResult:
        file_path = args["filePath"]
        offset = args.get("offset")
        limit = args.get("limit")

        # Resolve path with hallucination correction
        resolved_path = resolve_safe_path(file_path, ctx)

        allowed, _ = await check_file_permission(ctx, resolved_path)
        if not allowed:
            return ToolExecResult(
                output=f"Permission denied: {resolved_path}",
                title="read [denied]",
            )

        if not os.path.isfile(resolved_path):
            hint = ""
            # Provide hints for common hallucinated paths
            if file_path != resolved_path:
                hint = (
                    f"\n\nNote: The path you provided ('{file_path}') was auto-corrected "
                    f"to '{resolved_path}'. The actual working directory is '{ctx.cwd}'. "
                    f"Please use the correct absolute path or a relative path."
                )
            return ToolExecResult(
                output=f"Error: file not found: {resolved_path}{hint}",
                title="read [error]",
            )

        try:
            with open(resolved_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError as e:
            return ToolExecResult(
                output=f"Error reading file '{resolved_path}': {e}",
                title="read [error]",
            )

        total_lines = len(lines)
        start = 0
        end = total_lines

        if offset is not None:
            start = max(0, int(offset) - 1)
        if limit is not None:
            end = min(end, start + int(limit))

        selected = lines[start:end]
        output_lines = [f"{start + i + 1}: {line.rstrip()}" for i, line in enumerate(selected)]

        fname = os.path.basename(resolved_path)
        header = f"{resolved_path} (lines {start + 1}-{start + len(selected)}/{total_lines})"
        output = header + "\n" + "\n".join(output_lines)

        if start + len(selected) < total_lines:
            output += f"\n... ({total_lines - (start + len(selected))} more lines)"

        return ToolExecResult(
            output=output,
            title=f"read [{fname}]",
            metadata={"lines": len(selected), "total": total_lines},
        )
