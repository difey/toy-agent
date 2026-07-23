"""Diff service — workspace snapshot, diff computation, and mapping management.

Tool-agnostic: detects file changes by comparing SHA256 hashes of file contents
before and after an AI round, rather than tracking specific tool calls.

Binary file handling: binary files (detected by null bytes in first 8 KB) are
hashed but their content is NOT cached in memory. They appear in diffs with
a "binary": true flag and no line-level diff text.
"""

import difflib
import hashlib
import json
import os
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

from nano_claude.infra.session import get_diff_dir


def _compute_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _compute_sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_binary_file(abs_path: str) -> bool:
    """Detect binary files by checking for null bytes in first 8 KB (same heuristic as git)."""
    try:
        with open(abs_path, "rb") as f:
            chunk = f.read(8192)
        return b"\0" in chunk
    except OSError:
        return False


def _is_excluded(rel_path: str) -> bool:
    """Check if a relative path should be excluded from scanning."""
    excluded_dirs = {
        ".git", "node_modules", "__pycache__", ".venv", "venv",
        "dist", "build", ".DS_Store", ".mypy_cache", ".pytest_cache",
        ".egg-info", ".tox", ".idea", ".vscode", ".hg", ".svn",
    }
    parts = rel_path.replace("\\", "/").split("/")
    for part in parts:
        if part in excluded_dirs:
            return True
        if part.endswith(".pyc"):
            return True
    return False


def _get_git_tracked_files(cwd: str) -> set[str]:
    """Return set of absolute paths for all git-tracked files."""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "ls-files", "--cached", "--others", "--exclude-standard"],
            capture_output=True, text=True, check=True, timeout=30,
        )
        files: set[str] = set()
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            abs_path = os.path.normpath(os.path.join(cwd, line))
            if os.path.isfile(abs_path):
                files.add(abs_path)
        return files
    except (subprocess.SubprocessError, FileNotFoundError, TimeoutError):
        return set()


def _scan_directory(cwd: str) -> set[str]:
    """Recursively scan directory for files, excluding common non-source dirs."""
    files: set[str] = set()
    cwd_str = str(Path(cwd).resolve())
    for root, dirs, names in os.walk(cwd_str):
        rel_root = os.path.relpath(root, cwd_str)
        dirs[:] = [d for d in dirs if not _is_excluded(
            os.path.join(rel_root, d) if rel_root != "." else d
        )]
        for name in names:
            rel_path = os.path.join(rel_root, name) if rel_root != "." else name
            if _is_excluded(rel_path):
                continue
            abs_path = os.path.normpath(os.path.join(root, name))
            if os.path.isfile(abs_path):
                files.add(abs_path)
    return files


def take_snapshot(cwd: str) -> tuple[dict[str, str | None], dict[str, str], set[str]]:
    """Take a SHA256 hash snapshot of all trackable files in the workspace.

    Returns a tuple of (hash_dict, content_dict, binary_set):
      - hash_dict: maps absolute file paths to their SHA256 hash (or None if unreadable)
      - content_dict: maps absolute file paths to their full text content (text files only)
      - binary_set: set of absolute file paths that are binary (no content cached)
    """
    resolved_cwd = str(Path(cwd).resolve())

    tracked = _get_git_tracked_files(resolved_cwd)
    file_paths = tracked if tracked else _scan_directory(resolved_cwd)

    hash_snapshot: dict[str, str | None] = {}
    content_snapshot: dict[str, str] = {}
    binary_set: set[str] = set()

    for abs_path in sorted(file_paths):
        try:
            if _is_binary_file(abs_path):
                # Binary file: hash only, no content cached
                with open(abs_path, "rb") as f:
                    raw = f.read()
                hash_snapshot[abs_path] = _compute_sha256_bytes(raw)
                binary_set.add(abs_path)
            else:
                # Text file: hash + content cached for diff generation
                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                hash_snapshot[abs_path] = _compute_sha256(content)
                content_snapshot[abs_path] = content
        except (OSError, PermissionError):
            hash_snapshot[abs_path] = None

    return hash_snapshot, content_snapshot, binary_set


def _generate_unified_diff_for_git(cwd: str, rel_path: str) -> str | None:
    """Use git diff to generate unified diff for a tracked file."""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "diff", "--no-color", "-U5", "--", rel_path],
            capture_output=True, text=True, check=True, timeout=30,
        )
        diff = result.stdout
        if diff and not diff.endswith("\n"):
            diff += "\n"
        return diff
    except (subprocess.SubprocessError, FileNotFoundError, TimeoutError):
        return None


def _generate_unified_diff_manual(
    old_content: str | None, new_content: str | None,
    from_path: str, to_path: str,
) -> str:
    """Manually generate unified diff using difflib."""
    old_lines = (old_content or "").splitlines(keepends=True)
    new_lines = (new_content or "").splitlines(keepends=True)

    from_name = from_path if from_path.startswith("/") else f"a/{from_path}"
    to_name = to_path if to_path.startswith("/") else f"b/{to_path}"

    diff_lines = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile=from_name, tofile=to_name,
        n=5,
    ))
    result = "".join(diff_lines)
    if result and not result.endswith("\n"):
        result += "\n"
    return result


def _count_diff_stats(diff_text: str) -> tuple[int, int]:
    """Count insertions and deletions in unified diff, excluding headers."""
    insertions = 0
    deletions = 0
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            insertions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
    return insertions, deletions


def compute_diff(
    cwd: str,
    before: dict[str, str | None],
    after: dict[str, str | None],
    before_content: dict[str, str] | None = None,
    binary_set: set[str] | None = None,
) -> dict | None:
    """Compare before and after snapshots, return diff data or None.

    Args:
        cwd: Working directory (for computing relative paths)
        before: Snapshot dict from take_snapshot() before the round
        after: Snapshot dict from take_snapshot() after the round
        before_content: Content dict from take_snapshot() before the round
                        (needed for non-git deleted/modified file diffs)
        binary_set: Set of absolute file paths that are binary files.
                    Binary files skip line-level diff generation.

    Returns:
        Dict with 'summary' and 'files' keys, or None if no changes.
    """
    resolved_cwd = str(Path(cwd).resolve())
    all_paths = set(before.keys()) | set(after.keys())
    files_data: list[dict] = []
    binary = binary_set or set()

    for abs_path in sorted(all_paths):
        before_hash = before.get(abs_path)
        after_hash = after.get(abs_path)

        if before_hash == after_hash:
            continue  # No change

        rel_path = os.path.relpath(abs_path, resolved_cwd)

        # Determine status based on hash presence
        if before_hash is None and after_hash is not None:
            status = "added"
        elif before_hash is not None and after_hash is None:
            status = "deleted"
        elif before_hash is not None and after_hash is not None and before_hash != after_hash:
            status = "modified"
        else:
            continue

        # ── Binary file handling ──────────────────────────────────────
        if abs_path in binary:
            if status == "modified":
                # Try git diff first — it handles binary well
                git_diff = _generate_unified_diff_for_git(resolved_cwd, rel_path)
                if git_diff:
                    ins, dels = _count_diff_stats(git_diff)
                    files_data.append({
                        "path": rel_path,
                        "status": status,
                        "insertions": ins,
                        "deletions": dels,
                        "diff": git_diff,
                        "binary": True,
                    })
                    continue

            # No diff content available for binary added/deleted
            files_data.append({
                "path": rel_path,
                "status": status,
                "insertions": 0,
                "deletions": 0,
                "diff": "",
                "binary": True,
            })
            continue

        # ── Text file handling ────────────────────────────────────────
        if status == "added":
            try:
                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    new_content = f.read()
            except OSError:
                new_content = ""
            diff_text = _generate_unified_diff_manual(
                None, new_content, "/dev/null", rel_path,
            )
        elif status == "deleted":
            old_content = (before_content or {}).get(abs_path, "")
            diff_text = _generate_unified_diff_manual(
                old_content, None, rel_path, "/dev/null",
            )
        else:  # modified
            git_diff = _generate_unified_diff_for_git(resolved_cwd, rel_path)
            if git_diff:
                diff_text = git_diff
            else:
                old_content = (before_content or {}).get(abs_path, "")
                try:
                    with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                        new_content = f.read()
                except OSError:
                    new_content = ""
                diff_text = _generate_unified_diff_manual(
                    old_content, new_content, rel_path, rel_path,
                )

        insertions, deletions = _count_diff_stats(diff_text)
        files_data.append({
            "path": rel_path,
            "status": status,
            "insertions": insertions,
            "deletions": deletions,
            "diff": diff_text,
        })

    if not files_data:
        return None

    total_insertions = sum(f["insertions"] for f in files_data)
    total_deletions = sum(f["deletions"] for f in files_data)

    return {
        "summary": {
            "files_changed": len(files_data),
            "insertions": total_insertions,
            "deletions": total_deletions,
        },
        "files": files_data,
    }


def save_diff(cwd: str, diff_data: dict, segment_key: str, session_file: str) -> str:
    """Save diff data to disk and update mapping. Returns the diff filename."""
    diff_dir = get_diff_dir(cwd)
    timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%S")
    unique_id = uuid.uuid4().hex[:8]
    filename = f"{timestamp}-{unique_id}.json"
    filepath = os.path.join(diff_dir, filename)

    wrapped = {
        "version": 1,
        "timestamp": timestamp,
        "session_file": session_file,
        "message_segment_key": segment_key,
        "summary": diff_data["summary"],
        "files": diff_data["files"],
    }

    Path(filepath).write_text(
        json.dumps(wrapped, ensure_ascii=False, indent=2)
    )

    # Update mapping — acts as lightweight metadata index for diff files
    mapping = _load_mapping(cwd)
    mapping.setdefault("mappings", []).append({
        "segment_key": segment_key,
        "diff_filename": filename,
        "session_file": session_file,
        "timestamp": timestamp,
    })
    _save_mapping(cwd, mapping)

    return filename


def get_diff(cwd: str, diff_filename: str) -> dict | None:
    """Read and return a specific diff file."""
    diff_dir = get_diff_dir(cwd)
    filepath = os.path.join(diff_dir, diff_filename)
    if not os.path.isfile(filepath):
        return None
    try:
        return json.loads(Path(filepath).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def get_diff_for_segment(cwd: str, segment_key: str) -> dict | None:
    """Find and return the diff for a specific segment key."""
    mapping = _load_mapping(cwd)
    for entry in mapping.get("mappings", []):
        if entry["segment_key"] == segment_key:
            return get_diff(cwd, entry["diff_filename"])
    return None


def list_diffs(cwd: str) -> list[dict]:
    """Return list of diff summaries, most recent first."""
    mapping = _load_mapping(cwd)
    summaries = []
    for entry in reversed(mapping.get("mappings", [])):
        diff_data = get_diff(cwd, entry["diff_filename"])
        if diff_data:
            summaries.append({
                "segment_key": entry["segment_key"],
                "diff_filename": entry["diff_filename"],
                "summary": diff_data["summary"],
            })
    return summaries


def list_diffs_for_session(cwd: str, session_file_basename: str) -> list[dict]:
    """Return list of diff summaries for a specific session file, most recent first.

    Filters diffs by matching the ``session_file`` field stored in each
    persisted diff payload against the given basename.
    """
    mapping = _load_mapping(cwd)
    summaries = []
    for entry in reversed(mapping.get("mappings", [])):
        diff_data = get_diff(cwd, entry["diff_filename"])
        if diff_data and diff_data.get("session_file") == session_file_basename:
            summaries.append({
                "segment_key": entry["segment_key"],
                "diff_filename": entry["diff_filename"],
                "summary": diff_data["summary"],
            })
    return summaries


def _load_mapping(cwd: str) -> dict:
    """Load the diff mapping file."""
    diff_dir = get_diff_dir(cwd)
    mapping_path = os.path.join(diff_dir, "mapping.json")
    if not os.path.isfile(mapping_path):
        return {"version": 1, "mappings": []}
    try:
        return json.loads(Path(mapping_path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "mappings": []}


def _save_mapping(cwd: str, mapping: dict) -> None:
    """Save the diff mapping file."""
    diff_dir = get_diff_dir(cwd)
    mapping_path = os.path.join(diff_dir, "mapping.json")
    Path(mapping_path).write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2)
    )
