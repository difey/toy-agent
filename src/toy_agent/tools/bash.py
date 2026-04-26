import asyncio
import os
import re
import shlex

from toy_agent.tool import Tool, ToolContext, ToolExecResult


DANGEROUS_PATTERNS = [
    r"rm\s+-rf\s+/",
    r"mkfs\.",
    r"dd\s+if=",
    r":\(\)\s*\{.*:\|:&\s*\};:",
    r"chmod\s+-R\s+777\s+/",
    r">\s*/dev/sd[a-z]",
    r">\s*/dev/nvme",
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

        if not self._is_safe(command, workdir):
            return ToolExecResult(
                output=f"Blocked: command '{command}' matches dangerous pattern.",
                title="bash [blocked]",
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

    def _is_safe(self, command: str, workdir: str) -> bool:
        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, command):
                return False

        interactive_commands = {"vim", "vi", "nano", "less", "more", "top", "htop", "ssh"}
        try:
            tokens = shlex.split(command)
        except ValueError:
            tokens = command.split()
        if tokens and tokens[0] in interactive_commands:
            return False

        return True
