import os
import re

from nano_claude.tool import (
    Tool,
    ToolContext,
    ToolExecResult,
    check_file_permission,
    resolve_safe_path,
)


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
                    "description": "Path to the file to modify. Can be relative to cwd or absolute.",
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

        # Resolve path with hallucination correction
        resolved_path = resolve_safe_path(file_path, ctx)

        # In plan mode, only allow editing .md files under .session/
        if ctx.mode == "plan":
            session_dir = os.path.join(ctx.cwd, ".session")
            resolved_lower = resolved_path.lower()
            if not resolved_lower.endswith(".md"):
                return ToolExecResult(
                    output=f"Plan mode: can only edit .md files. Refused to edit '{resolved_path}'",
                    title="edit [plan mode]",
                )
            if not resolved_path.startswith(session_dir):
                return ToolExecResult(
                    output=(
                        f"Plan mode: can only edit .md files under .session/ directory. "
                        f"Refused to edit '{resolved_path}'."
                    ),
                    title="edit [plan mode]",
                )

        allowed, _ = await check_file_permission(ctx, resolved_path)
        if not allowed:
            return ToolExecResult(
                output=f"Permission denied: {resolved_path}",
                title="edit [denied]",
            )

        if not os.path.isfile(resolved_path):
            hint = ""
            if file_path != resolved_path:
                hint = (
                    f"\n\nNote: The path you provided ('{file_path}') was auto-corrected "
                    f"to '{resolved_path}'. The actual working directory is '{ctx.cwd}'. "
                    f"Please use the correct absolute path or a relative path."
                )
            return ToolExecResult(
                output=f"Error: file not found: {resolved_path}{hint}",
                title="edit [error]",
            )

        try:
            with open(resolved_path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError as e:
            return ToolExecResult(
                output=f"Error reading file '{resolved_path}': {e}",
                title="edit [error]",
            )

        count = content.count(old_string)
        if count == 0:
            return ToolExecResult(
                output=f"Error: oldString not found in {resolved_path}",
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
            with open(resolved_path, "w", encoding="utf-8") as f:
                f.write(new_content)
        except OSError as e:
            return ToolExecResult(
                output=f"Error writing file '{resolved_path}': {e}",
                title="edit [error]",
            )

        num = count if replace_all else 1
        fname = os.path.basename(resolved_path)
        return ToolExecResult(
            output=f"Successfully replaced {num} occurrence(s) in {resolved_path}",
            title=f"edit [{fname}]",
        )
