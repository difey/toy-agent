import os
import re

from toy_agent.tool import Tool, ToolContext, ToolExecResult, check_file_permission


class EditTool(Tool):
    @property
    def name(self) -> str:
        return "edit"

    @property
    def description(self) -> str:
        return (
            "Perform exact string replacements in a file. "
            "When editing text, ensure you preserve the exact indentation (tabs/spaces) as it appears. "
            "ALWAYS prefer editing existing files in the codebase. NEVER write new files unless explicitly required. "
            "The edit will FAIL if oldString is not unique or not found."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "filePath": {
                    "type": "string",
                    "description": "Absolute path to the file to modify",
                },
                "oldString": {
                    "type": "string",
                    "description": "The text to replace",
                },
                "newString": {
                    "type": "string",
                    "description": "The text to replace it with",
                },
                "replaceAll": {
                    "type": "boolean",
                    "description": "Replace all occurrences of oldString (default false)",
                },
            },
            "required": ["filePath", "oldString", "newString"],
        }

    async def execute(self, args: dict, ctx: ToolContext) -> ToolExecResult:
        file_path = args["filePath"]
        old_string = args["oldString"]
        new_string = args["newString"]
        replace_all = args.get("replaceAll", False)

        allowed, _ = await check_file_permission(ctx, file_path)
        if not allowed:
            return ToolExecResult(
                output=f"Permission denied: {file_path}",
                title="edit [denied]",
            )

        if not os.path.isfile(file_path):
            return ToolExecResult(
                output=f"Error: file not found: {file_path}",
                title="edit [error]",
            )

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError as e:
            return ToolExecResult(
                output=f"Error reading file '{file_path}': {e}",
                title="edit [error]",
            )

        count = content.count(old_string)
        if count == 0:
            return ToolExecResult(
                output=f"Error: oldString not found in {file_path}",
                title="edit [error]",
            )
        if not replace_all and count > 1:
            return ToolExecResult(
                output=f"Error: Found {count} matches for oldString. Provide more surrounding lines "
                       f"in oldString to identify the correct match, or use replaceAll=true.",
                title="edit [error]",
            )

        new_content = content.replace(old_string, new_string) if replace_all else content.replace(old_string, new_string, 1)

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_content)
        except OSError as e:
            return ToolExecResult(
                output=f"Error writing file '{file_path}': {e}",
                title="edit [error]",
            )

        num = count if replace_all else 1
        fname = os.path.basename(file_path)
        return ToolExecResult(
            output=f"Successfully replaced {num} occurrence(s) in {file_path}",
            title=f"edit [{fname}]",
        )
