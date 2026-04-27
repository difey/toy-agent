import asyncio
import os
import re
import shlex
from typing import Optional

from nano_claude.tool import Tool, ToolContext, ToolExecResult, resolve_safe_path


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

# Patterns for file-search commands that can be very slow on large codebases
# When these are detected, the tool will add protections (exclusions, shorter timeout, warning)
SEARCH_COMMAND_PATTERNS = [
    # find commands (recursive file/dir search)
    (r"\bfind\s+\.", "recursive file search via `find`"),
    # recursive grep
    (r"\bgrep\s+-[a-zA-Z]*r", "recursive content search via `grep -r`"),
    (r"\bgrep\s+-[a-zA-Z]*R", "recursive content search via `grep -R`"),
    (r"\bgrep\s+-[a-zA-Z]*[0-9]*[rR]", "recursive content search via `grep`"),
    # ripgrep / ag / ack / rg
    (r"\brg\s+", "content search via `rg` (ripgrep)"),
    (r"\bag\s+", "content search via `ag` (silver searcher)"),
    (r"\back\s+", "content search via `ack`"),
    # fd (modern find alternative)
    (r"\bfd\s+", "file search via `fd`"),
    # locate/mlocate
    (r"\blocate\s+", "file search via `locate`"),
    # du / ls with recursive flags on large dirs
    (r"\bdu\s+-[a-zA-Z]*[hH].*\..*", "disk usage scan"),
]

# Heavy directories that should be auto-excluded from file searches
HEAVY_DIRS_TO_EXCLUDE = [
    ".git",
    "node_modules",
    ".venv",
    "venv",
    ".tox",
    "build",
    "dist",
    ".next",
    "__pycache__",
    ".pytest_cache",
    ".cache",
    "target",       # Rust build artifacts
    ".bundle",      # Ruby bundler
    "vendor",       # Go / PHP vendor
    ".eggs",
    "*.egg-info",
    ".svn",
    ".hg",
    ".sass-cache",
    ".mypy_cache",
    ".ruff_cache",
    ".hypothesis",
    ".ipynb_checkpoints",
]

# Shorter timeout for file-search-type commands (seconds)
SEARCH_COMMAND_TIMEOUT = 30


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

        # Resolve workdir with hallucination correction
        workdir = resolve_safe_path(workdir, ctx)

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

        # --- File-search command protection ---
        search_reason, search_timeout = self._detect_search_command(command)
        if search_reason:
            # Auto-add exclusion paths to prevent scanning heavy directories
            enriched_command = self._auto_exclude_heavy_dirs(command, workdir)
            if enriched_command != command:
                command = enriched_command

            # Use shorter timeout for search commands
            timeout = search_timeout or SEARCH_COMMAND_TIMEOUT
            warning = (
                f"[Search guard] Detected: {search_reason}. "
                f"Using {timeout}s timeout instead of the default 120s. "
            )
            if enriched_command != command:
                warning += f"Auto-excluded heavy dirs ({', '.join(HEAVY_DIRS_TO_EXCLUDE)}). "
            warning += (
                "Consider using the dedicated `glob` (for file patterns) or "
                "`grep` (for content search) tools instead — they are faster and safer."
            )
        else:
            timeout = 120
            warning = ""

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
                executable="/bin/bash",
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            extra = ""
            if search_reason:
                extra = (
                    f"\n\nTip: This was a file-search command ({search_reason}) "
                    f"which timed out after {timeout}s. "
                    f"Try using the `glob` tool for filename searches or `grep` tool "
                    f"for content searches instead of `bash` — they handle large codebases "
                    f"more efficiently."
                )
            return ToolExecResult(
                output=f"Command timed out after {timeout}s: {command}{extra}",
                title="bash [timeout]",
            )

        out = (stdout.decode("utf-8", errors="replace") or "") + (
            stderr.decode("utf-8", errors="replace") or ""
        )
        out = out.strip() or "(no output)"

        # Prepend warning if search command was detected
        if warning:
            out = warning + "\n" + out

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

    def _detect_search_command(self, command: str) -> tuple[str, Optional[int]]:
        """Detect if the command is a file-search type command.
        
        Returns (reason_string, suggested_timeout) if detected, or ("", None) if not.
        """
        for pattern, reason in SEARCH_COMMAND_PATTERNS:
            if re.search(pattern, command):
                return reason, SEARCH_COMMAND_TIMEOUT
        return "", None

    def _auto_exclude_heavy_dirs(self, command: str, workdir: str) -> str:
        """Auto-append exclusion patterns for heavy directories when doing file searches.
        
        For `find` commands, adds `-not -path` exclusions.
        For `grep -r` / `rg` commands, adds `--exclude-dir` flags.
        """
        # Determine which heavy dirs actually exist in the workspace
        existing_heavy_dirs = []
        for d in HEAVY_DIRS_TO_EXCLUDE:
            if d.startswith("*"):
                # Glob-like pattern, skip for now (too complex)
                continue
            full_path = os.path.join(workdir, d)
            if os.path.isdir(full_path):
                existing_heavy_dirs.append(d)

        if not existing_heavy_dirs:
            return command

        # For `find` commands
        if re.search(r"\bfind\s+", command):
            exclusion_parts = []
            for d in existing_heavy_dirs:
                exclusion_parts.append(f'-not -path "*/{d}/*" -not -path "*/{d}"')
            if exclusion_parts:
                exclusion_str = " ".join(exclusion_parts)
                # Insert exclusions before any -exec or -print or end of command
                # Simple approach: append before potential trailing parts
                command = command.rstrip() + " " + exclusion_str
            return command

        # For `grep -r` / `rg` / `ag` / `ack` commands
        grep_pattern = re.compile(r"\b(rg|ag|ack|grep)\b")
        if grep_pattern.search(command):
            exclusion_parts = []
            for d in existing_heavy_dirs:
                exclusion_parts.append(f'--exclude-dir="{d}"')
            if exclusion_parts:
                exclusion_str = " ".join(exclusion_parts)
                # Insert after the command name
                for cmd_name in ["rg ", "ag ", "ack ", "grep "]:
                    if cmd_name in command:
                        # Insert exclusion flags right after the command name
                        command = command.replace(
                            cmd_name,
                            f"{cmd_name}{exclusion_str} ",
                            1,
                        )
                        break
            return command

        # For `fd` commands
        if re.search(r"\bfd\s+", command):
            exclusion_parts = []
            for d in existing_heavy_dirs:
                exclusion_parts.append(f'--exclude="{d}"')
            if exclusion_parts:
                exclusion_str = " ".join(exclusion_parts)
                command = command.replace("fd ", f"fd {exclusion_str} ", 1)
            return command

        return command
