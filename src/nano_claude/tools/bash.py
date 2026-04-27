import asyncio
import os
import re
import shlex

from nano_claude.tool import Tool, ToolContext, ToolExecResult


DANGEROUS_PATTERNS = [
    (r"rm\s+-rf\s+/", "recursively delete root directory"),
    (r"mkfs\.", "format filesystem"),
    (r"dd\s+if=", "raw disk write"),
    (r":\(\)\s*\{.*:\|:&\s*\};:", "fork bomb"),
    (r"chmod\s+-R\s+777\s+/", "recursive world-writable permissions on root"),
    (r">\s*/dev/sd[a-z]", "overwrite block device"),
    (r">\s*/dev/nvme", "overwrite NVMe device"),
    (r"sudo\s+rm\s+-rf\s+/", "sudo delete root"),
]


class BashTool(Tool):
    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return (
            "Execute a shell command in the working directory. "
            "The command runs in a persistent shell session with preserved working directory state. "
            "Commands timeout after 120 seconds. Output is truncated at 50KB. "
            "Use the 'description' parameter to briefly describe what the command does (5-10 words)."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute",
                },
                "workdir": {
                    "type": "string",
                    "description": "Working directory for the command. Defaults to the project working directory.",
                },
                "description": {
                    "type": "string",
                    "description": "5-10 word description of what the command does",
                },
            },
            "required": ["command"],
        }

    async def execute(self, args: dict, ctx: ToolContext) -> ToolExecResult:
        command = args["command"]
        workdir = args.get("workdir", ctx.cwd)
        desc = args.get("description", "")

        danger_reason = self._danger_reason(command)
        if danger_reason and ctx.permission_callback:
            result = await ctx.permission_callback(
                "bash", command, danger_reason
            )
            if result == "deny":
                return ToolExecResult(
                    output=f"Blocked by user: {danger_reason}",
                    title="bash [denied]",
                )

        if not os.path.isdir(workdir):
            return ToolExecResult(
                output=f"Error: workdir '{workdir}' does not exist.",
                title="bash [error]",
            )

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
                executable="/bin/bash",
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=120
            )
        except asyncio.TimeoutError:
            return ToolExecResult(
                output=f"Command timed out after 120s: {command}",
                title="bash [timeout]",
            )

        out = (stdout.decode("utf-8", errors="replace") or "") + (
            stderr.decode("utf-8", errors="replace") or ""
        )
        out = out.strip() or "(no output)"

        title = f"bash [{desc}]" if desc else "bash"

        if len(out) > 50000:
            out = out[:50000] + "\n... (output truncated at 50KB)"

        return ToolExecResult(output=out, title=title, metadata={"exit_code": proc.returncode})

    def _danger_reason(self, command: str) -> str:
        for pattern, reason in DANGEROUS_PATTERNS:
            if re.search(pattern, command):
                return reason

        interactive_commands = {"vim", "vi", "nano", "less", "more", "top", "htop", "ssh"}
        try:
            tokens = shlex.split(command)
        except ValueError:
            tokens = command.split()
        if tokens and tokens[0] in interactive_commands:
            return f"interactive command: {tokens[0]}"

        return ""
