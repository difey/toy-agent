"""Path resolution helpers, including correction of LLM-hallucinated base paths."""

import os

from nano_claude.core.tool_contracts import ToolContext

# Common hallucinated base paths that LLMs tend to generate instead of the real cwd.
# These are paths commonly seen in training data (CodinGame, LeetCode, cloud IDEs, etc.).
HALLUCINATED_BASE_PATHS = [
    "/workspace",
    "/project",
    "/app",
    "/code",
    "/home/user",
    "/home/project",
    "/home/developer",
    "/root",
    "/src",
    "/source",
    "/Users/user",
    "/home/coder",
    "/sandbox",
]

# How many path components to strip when a hallucinated base is detected.
# E.g. /workspace/src/foo/bar.py with cwd=/real/path → /real/path/src/foo/bar.py
# If the hallucinated path has extra prefix components, we strip them.
_HALLUCINATION_STRIP_PREFIXES = ["src/", "source/", "app/", "code/"]


def _resolve_path(path: str, cwd: str) -> str:
    p = os.path.join(cwd, path) if not os.path.isabs(path) else path
    return os.path.realpath(p)


def correct_hallucinated_path(path: str, cwd: str) -> str:
    """Detect and correct paths that look like LLM hallucinations.

    The LLM sometimes generates paths like `/workspace/src/foo/bar.py` even
    though the actual project root is something completely different (e.g.
    `/Users/name/real-project/`). This function detects such cases and
    remaps the path to the real cwd.

    Returns the corrected path if a hallucination was detected and fixed,
    or the original path otherwise.
    """
    if not os.path.isabs(path):
        return path  # Relative paths are fine

    resolved_cwd = os.path.realpath(cwd)

    # If the path already exists and is within cwd, no correction needed
    try:
        if os.path.exists(path):
            resolved = os.path.realpath(path)
            if _is_within_cwd(resolved, resolved_cwd):
                return path  # Already correct
    except (OSError, ValueError):
        pass

    corrected = path

    # Check if the path starts with a known hallucinated base
    for base in HALLUCINATED_BASE_PATHS:
        if path.startswith(base + "/") or path == base:
            rel_part = path[len(base):].lstrip("/")
            corrected = os.path.join(resolved_cwd, rel_part)
            break

    # Also check for paths that look like they dropped the project root entirely
    # e.g. "/src/nano_claude/cli.py" instead of "/real/cwd/src/nano_claude/cli.py"
    if corrected == path:
        for prefix in _HALLUCINATION_STRIP_PREFIXES:
            check_path = "/" + prefix.rstrip("/")
            if path.startswith(check_path):
                rel_part = path[len(check_path):].lstrip("/")
                corrected = os.path.join(resolved_cwd, prefix.rstrip("/"), rel_part)
                break

    return corrected


def resolve_safe_path(path: str, ctx: ToolContext) -> str:
    """Resolve a file path with hallucination correction.

    Steps:
    1. If relative, join with ctx.cwd
    2. Apply hallucination correction (remap /workspace/... → ctx.cwd/...)
    3. Resolve to real path

    Returns the resolved absolute path.
    """
    # Step 1: Make absolute if relative
    if not os.path.isabs(path):
        path = os.path.join(ctx.cwd, path)

    # Step 2: Correct hallucinated bases
    corrected = correct_hallucinated_path(path, ctx.cwd)

    # Step 3: Resolve to real path
    try:
        return os.path.realpath(corrected)
    except OSError:
        return corrected


def _is_within_cwd(path: str, cwd: str) -> bool:
    try:
        resolved_path = os.path.realpath(path)
        resolved_cwd = os.path.realpath(cwd)
        common = os.path.commonpath([resolved_path, resolved_cwd])
        return common == resolved_cwd
    except (ValueError, OSError):
        return False


async def check_file_permission(
    ctx: ToolContext, file_path: str
) -> tuple[bool, str]:
    resolved_cwd = os.path.realpath(ctx.cwd)
    resolved_path = resolve_safe_path(file_path, ctx)

    if _is_within_cwd(resolved_path, resolved_cwd):
        return True, ""

    # Always allow access to the session directory (home dir storage)
    if ctx.session_dir and _is_within_cwd(resolved_path, ctx.session_dir):
        return True, ""

    if resolved_path in ctx.allowed_files:
        return True, ""

    if ctx.permission_callback is None:
        return True, ""

    result = await ctx.permission_callback("file", file_path, resolved_path)
    if result == "allow_always":
        ctx.allowed_files.add(resolved_path)
        return True, ""
    return result == "allow", result
