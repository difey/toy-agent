"""Tool contract types shared between the agent core and tool implementations."""

import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

# PermissionCallback: returns "allow" | "deny" | "allow_always"
PermissionCallback = Callable[[str, str, str], Awaitable[str]]

AskUserCallback = Callable[[str, str, list[dict], bool], Awaitable[list[str]]]


@dataclass
class ToolExecResult:
    output: str
    title: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class FileReadRegistry:
    """Tracks file reads per agent to detect stale content before modifications.

    Each agent (including sub-agents) gets its own registry via ToolContext.
    Staleness is checked against on-disk mtime, which naturally catches
    cross-agent conflicts during parallel execution.
    """

    _reads: dict[str, float | None] = field(default_factory=dict)
    # resolved_path -> mtime at read time (None = verified non-existent)

    def record_read(self, path: str, mtime: float | None) -> None:
        """Record that a file was read.

        Args:
            path: Resolved absolute file path
            mtime: File's mtime at read time, or None if file didn't exist
        """
        self._reads[os.path.normpath(path)] = mtime

    def check_modification_allowed(self, path: str) -> tuple[bool, str]:
        """Check if modifying 'path' is safe.

        Returns (allowed: bool, reason: str).
        On success, reason is empty string.
        """
        normalized = os.path.normpath(path)
        exists = os.path.exists(normalized)

        if exists:
            if normalized not in self._reads:
                return False, f"File '{path}' has not been read. Use the read tool to read the file first."

            read_mtime = self._reads[normalized]
            if read_mtime is None:
                return False, f"File '{path}' was created by another agent since it was last verified as non-existent. Use the read tool to check the current state."

            current_mtime = os.path.getmtime(normalized)
            if current_mtime != read_mtime:
                return False, f"File '{path}' was modified after it was last read. Use the read tool to re-read the latest content."

            return True, ""
        else:
            if normalized in self._reads:
                read_mtime = self._reads[normalized]
                if read_mtime is None:
                    return True, ""
                else:
                    return False, f"File '{path}' no longer exists (deleted after it was last read)."
            else:
                return False, f"Cannot create '{path}' without verifying it doesn't exist. Use the read tool to check the path first."

    def has_read(self, path: str) -> bool:
        """Check if a path has been read (exists in registry)."""
        return os.path.normpath(path) in self._reads

    def get_stale_check_message(self, path: str) -> str | None:
        """For internal reads (edit/apply_patch): check content freshness.

        Returns None if the file is fresh (or was never read before).
        Returns an error message string if staleness is detected.

        Unlike check_modification_allowed, this does NOT require the file
        to have been read before — internal reads count as first-time reads.
        """
        normalized = os.path.normpath(path)
        if normalized not in self._reads:
            return None  # No prior read, allow (internal read will be the first)

        read_mtime = self._reads[normalized]
        if read_mtime is None:
            # Was verified non-existent, now it exists
            return f"File '{path}' was created by another agent since it was last verified as non-existent. Use the read tool to check the current state."

        if not os.path.exists(normalized):
            return f"File '{path}' no longer exists (deleted after it was last read)."

        current_mtime = os.path.getmtime(normalized)
        if current_mtime != read_mtime:
            return f"File '{path}' was modified after it was last read. Use the read tool to re-read the latest content."

        return None

    def record_modification(self, path: str) -> None:
        """Record that a file was successfully modified.

        Updates the registry with the current mtime so subsequent
        operations by the same agent can proceed.
        """
        normalized = os.path.normpath(path)
        if os.path.exists(normalized):
            try:
                self._reads[normalized] = os.path.getmtime(normalized)
            except OSError:
                self._reads[normalized] = None
        else:
            self._reads[normalized] = None  # file was deleted


@dataclass
class ToolContext:
    cwd: str
    session_dir: str = ""
    file_read_registry: "FileReadRegistry" = field(default_factory=lambda: FileReadRegistry())
    allowed_files: set = field(default_factory=set)
    permission_callback: PermissionCallback | None = None
    ask_user_callback: AskUserCallback | None = None
    mode: str = "build"  # "plan" or "build"
    parent_agent: Any | None = None  # Reference to parent Agent (for delegate tool)
    on_event: Callable[[str, dict], Awaitable[None]] | None = None  # Real-time event pusher (for sub-agent streaming)
    skill_store: Any | None = None  # SkillStore instance for the skill tool
