import os

from toy_agent.tool import Tool, ToolContext, ToolExecResult


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
                    "description": "Absolute path to the file to read",
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

        if not os.path.isfile(file_path):
            return ToolExecResult(
                output=f"Error: file not found: {file_path}",
                title="read [error]",
            )

        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError as e:
            return ToolExecResult(
                output=f"Error reading file '{file_path}': {e}",
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

        fname = os.path.basename(file_path)
        header = f"{file_path} (lines {start + 1}-{start + len(selected)}/{total_lines})"
        output = header + "\n" + "\n".join(output_lines)

        if start + len(selected) < total_lines:
            output += f"\n... ({total_lines - (start + len(selected))} more lines)"

        return ToolExecResult(
            output=output,
            title=f"read [{fname}]",
            metadata={"lines": len(selected), "total": total_lines},
        )
