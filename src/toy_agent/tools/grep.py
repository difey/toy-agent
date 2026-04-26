import asyncio
import fnmatch
import os
import re
import subprocess

from toy_agent.tool import Tool, ToolContext, ToolExecResult


class GrepTool(Tool):
    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return (
            "Fast content search tool that works with any codebase size. "
            "Searches file contents using regular expressions. "
            "Supports full regex syntax (e.g. 'log.*Error', 'function\\s+\\w+'). "
            "Returns file paths and line numbers with matches."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "The regex pattern to search for in file contents",
                },
                "path": {
                    "type": "string",
                    "description": "The directory to search in. Defaults to the working directory.",
                },
                "include": {
                    "type": "string",
                    "description": "File pattern to include (e.g. '*.py', '*.{ts,tsx}')",
                },
            },
            "required": ["pattern"],
        }

    async def execute(self, args: dict, ctx: ToolContext) -> ToolExecResult:
        pattern = args["pattern"]
        search_path = args.get("path", ctx.cwd)
        include = args.get("include")

        if not os.path.isdir(search_path):
            return ToolExecResult(
                output=f"Error: path not found: {search_path}",
                title="grep [error]",
            )

        cmd = ["rg", "--no-heading", "--line-number", "--color=never"]
        if include:
            cmd.extend(["--glob", include])
        cmd.append(pattern)
        cmd.append(search_path)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
        except FileNotFoundError:
            return self._fallback(pattern, search_path, include)
        except OSError:
            return self._fallback(pattern, search_path, include)

        out = stdout.decode("utf-8", errors="replace").strip() or "(no matches)"
        if len(out) > 30000:
            out = out[:30000] + "\n... (output truncated)"

        return ToolExecResult(
            output=out,
            title=f"grep [{pattern}]",
        )

    def _fallback(self, pattern: str, search_path: str, include: str | None) -> ToolExecResult:
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return ToolExecResult(
                output=f"Error: invalid regex pattern: {e}",
                title="grep [error]",
            )

        results = []
        for root, dirs, files in os.walk(search_path):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fname in files:
                if include and not self._match_glob(fname, include):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        for lineno, line in enumerate(f, 1):
                            if regex.search(line):
                                results.append(f"{fpath}:{lineno}:{line.rstrip()}")
                                if len(results) >= 200:
                                    break
                except OSError:
                    continue
                if len(results) >= 200:
                    break
            if len(results) >= 200:
                break

        output = "\n".join(results) if results else "(no matches)"
        return ToolExecResult(
            output=output,
            title=f"grep [{pattern}]",
        )

    def _match_glob(self, filename: str, pattern: str) -> bool:
        return fnmatch.fnmatch(filename, pattern)
