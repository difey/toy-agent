"""Diff service — workspace checkpoint (full-content snapshot) and rollback.

Tool-agnostic: detects file changes by comparing SHA256 hashes of file contents
before and after an AI round, then saves the full content of changed files for
rollback purposes.

Binary file handling: binary files (detected by null bytes in first 8 KB) are
hashed but their content is NOT persisted in checkpoints. They appear in diffs
with a "binary": true flag and are skipped during rollback.
"""

import hashlib
import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from nano_claude.infra.session import get_diff_dir

_CHECKPOINT_VERSION = 2
_MAX_KEEP = 10
_DIFF_TIMESTAMP_FMT = "%Y-%m-%dT%H-%M-%S"


# ── Hashing helpers ────────────────────────────────────────────────────────


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


# ── Git helpers ────────────────────────────────────────────────────────────


def _get_git_head_hash(cwd: str) -> str:
    """Get the full SHA of the current git HEAD commit.

    Returns an empty string if the cwd is not a git repository or has no HEAD
    commit (e.g. fresh repo before first commit).
    """
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True, timeout=15,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError, TimeoutError):
        return ""


# ── File scanning ──────────────────────────────────────────────────────────


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


# ── Snapshot ───────────────────────────────────────────────────────────────


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
                with open(abs_path, "rb") as f:
                    raw = f.read()
                hash_snapshot[abs_path] = _compute_sha256_bytes(raw)
                binary_set.add(abs_path)
            else:
                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                hash_snapshot[abs_path] = _compute_sha256(content)
                content_snapshot[abs_path] = content
        except (OSError, PermissionError):
            hash_snapshot[abs_path] = None

    return hash_snapshot, content_snapshot, binary_set


# ── Change detection ───────────────────────────────────────────────────────


def detect_file_changes(
    before: dict[str, str | None],
    after: dict[str, str | None],
    cwd: str,
    before_content: dict[str, str] | None = None,
    binary_set: set[str] | None = None,
) -> dict:
    """Compare before/after hash snapshots and classify changed files.

    Returns a dict with:
      - modified: {rel_path: before_content_string}
      - deleted:  {rel_path: before_content_string}
      - added:    [rel_path, ...]
      - binary:   [rel_path, ...]
      - files_changed: int
    """
    resolved_cwd = str(Path(cwd).resolve())
    all_paths = set(before.keys()) | set(after.keys())
    binary = binary_set or set()

    modified: dict[str, str] = {}
    deleted: dict[str, str] = {}
    added: list[str] = []
    binary_files: list[str] = []

    for abs_path in sorted(all_paths):
        before_hash = before.get(abs_path)
        after_hash = after.get(abs_path)

        if before_hash == after_hash:
            continue

        if before_hash is None and after_hash is not None:
            status = "added"
        elif before_hash is not None and after_hash is None:
            status = "deleted"
        elif before_hash is not None and after_hash is not None and before_hash != after_hash:
            status = "modified"
        else:
            continue

        rel_path = os.path.relpath(abs_path, resolved_cwd)

        if abs_path in binary:
            binary_files.append(rel_path)
            continue

        if status == "modified":
            content = (before_content or {}).get(abs_path, "")
            modified[rel_path] = content
        elif status == "deleted":
            content = (before_content or {}).get(abs_path, "")
            deleted[rel_path] = content
        else:  # added
            added.append(rel_path)

    return {
        "modified": modified,
        "deleted": deleted,
        "added": added,
        "binary": binary_files,
        "files_changed": len(modified) + len(deleted) + len(added) + len(binary_files),
    }


# ── Checkpoint CRUD ────────────────────────────────────────────────────────


def save_checkpoint(
    cwd: str,
    changed_files: dict,
    session_file: str,
    git_commit_hash: str,
) -> str:
    """Save a checkpoint to disk and update the mapping.

    Args:
        cwd: Working directory.
        changed_files: Dict from ``detect_file_changes()``.
        session_file: Basename of the session JSON file.
        git_commit_hash: Current git HEAD hash at snapshot time.

    Returns:
        The checkpoint filename (e.g. ``"2024-07-24T15-30-00-abc12345.json"``).
    """
    diff_dir = get_diff_dir(cwd)
    timestamp = datetime.utcnow().strftime(_DIFF_TIMESTAMP_FMT)
    unique_id = uuid.uuid4().hex[:8]
    filename = f"{timestamp}-{unique_id}.json"
    filepath = os.path.join(diff_dir, filename)

    checkpoint = {
        "version": _CHECKPOINT_VERSION,
        "timestamp": timestamp,
        "git_commit_hash": git_commit_hash,
        "session_file": session_file,
        "summary": {
            "files_changed": changed_files.get("files_changed", 0),
        },
        "files": {
            "modified": changed_files.get("modified", {}),
            "deleted": changed_files.get("deleted", {}),
            "added": changed_files.get("added", []),
            "binary": changed_files.get("binary", []),
        },
    }

    Path(filepath).write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2))

    # Update mapping
    mapping = _load_mapping(cwd)
    mapping.setdefault("mappings", []).append({
        "checkpoint_filename": filename,
        "session_file": session_file,
        "timestamp": timestamp,
        "git_commit_hash": git_commit_hash,
    })
    _save_mapping(cwd, mapping)

    return filename


def get_checkpoint(cwd: str, checkpoint_filename: str) -> dict | None:
    """Read and return a specific checkpoint file."""
    diff_dir = get_diff_dir(cwd)
    filepath = os.path.join(diff_dir, checkpoint_filename)
    if not os.path.isfile(filepath):
        return None
    try:
        return json.loads(Path(filepath).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def list_checkpoints(cwd: str) -> list[dict]:
    """Return list of checkpoint summaries, most recent first."""
    mapping = _load_mapping(cwd)
    summaries = []
    for entry in reversed(mapping.get("mappings", [])):
        checkpoint_filename = _entry_checkpoint_filename(entry)
        if not checkpoint_filename:
            continue
        cp = get_checkpoint(cwd, checkpoint_filename)
        if cp:
            files_list = _build_files_list(cp)
            summaries.append({
                "checkpoint_filename": checkpoint_filename,
                "summary": {
                    "files_changed": cp.get("summary", {}).get("files_changed", 0),
                    "files": files_list,
                },
            })
    return summaries


def list_checkpoints_for_session(cwd: str, session_file_basename: str) -> list[dict]:
    """Return list of checkpoint summaries for a specific session, most recent first."""
    mapping = _load_mapping(cwd)
    summaries = []
    for entry in reversed(mapping.get("mappings", [])):
        if entry.get("session_file") != session_file_basename:
            continue
        checkpoint_filename = _entry_checkpoint_filename(entry)
        if not checkpoint_filename:
            continue
        cp = get_checkpoint(cwd, checkpoint_filename)
        if cp:
            files_list = _build_files_list(cp)
            summaries.append({
                "checkpoint_filename": checkpoint_filename,
                "summary": {
                    "files_changed": cp.get("summary", {}).get("files_changed", 0),
                    "files": files_list,
                },
            })
    return summaries


def _build_files_list(checkpoint: dict) -> list[dict]:
    """Build a simplified file list from a checkpoint's files data."""
    files_list: list[dict] = []
    changed = checkpoint.get("files", {})
    for path in changed.get("modified", {}):
        files_list.append({"path": path, "status": "modified"})
    for path in changed.get("deleted", {}):
        files_list.append({"path": path, "status": "deleted"})
    for path in changed.get("added", []):
        files_list.append({"path": path, "status": "added"})
    for path in changed.get("binary", []):
        files_list.append({"path": path, "status": "binary"})
    return files_list


# ── Mapping helpers ────────────────────────────────────────────────────────


def _load_mapping(cwd: str) -> dict:
    """Load the checkpoint mapping file."""
    diff_dir = get_diff_dir(cwd)
    mapping_path = os.path.join(diff_dir, "mapping.json")
    if not os.path.isfile(mapping_path):
        return {"version": _CHECKPOINT_VERSION, "mappings": []}
    try:
        mapping = json.loads(Path(mapping_path).read_text(encoding="utf-8"))
        if _normalize_mapping(mapping):
            _save_mapping(cwd, mapping)
        return mapping
    except (json.JSONDecodeError, OSError):
        return {"version": _CHECKPOINT_VERSION, "mappings": []}


def _save_mapping(cwd: str, mapping: dict) -> None:
    """Save the checkpoint mapping file."""
    diff_dir = get_diff_dir(cwd)
    mapping_path = os.path.join(diff_dir, "mapping.json")
    Path(mapping_path).write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2)
    )


def _entry_checkpoint_filename(entry: dict) -> str:
    """Return checkpoint filename from mapping entry (supports legacy key names)."""
    filename = entry.get("checkpoint_filename")
    if isinstance(filename, str) and filename:
        return filename
    legacy_filename = entry.get("diff_filename")
    if isinstance(legacy_filename, str) and legacy_filename:
        return legacy_filename
    return ""


def _normalize_mapping(mapping: dict) -> bool:
    """Normalize mapping content to current schema; returns True if changed."""
    changed = False
    entries = mapping.get("mappings")
    if not isinstance(entries, list):
        mapping["mappings"] = []
        entries = mapping["mappings"]
        changed = True

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if "checkpoint_filename" not in entry:
            legacy_filename = entry.get("diff_filename")
            if isinstance(legacy_filename, str) and legacy_filename:
                entry["checkpoint_filename"] = legacy_filename
                changed = True

    if mapping.get("version") != _CHECKPOINT_VERSION:
        mapping["version"] = _CHECKPOINT_VERSION
        changed = True

    return changed


# ── Timestamp helpers ──────────────────────────────────────────────────────


def _checkpoint_timestamp_to_unix(ts_str: str) -> float:
    """Convert a checkpoint timestamp string (e.g. '2024-01-01T12-00-00') to Unix timestamp float."""
    dt = datetime.strptime(ts_str, _DIFF_TIMESTAMP_FMT)
    return dt.replace(tzinfo=timezone.utc).timestamp()


# ── Rollback ────────────────────────────────────────────────────────────────


class RollbackError(Exception):
    """Raised when rollback cannot proceed (e.g. hash mismatch)."""
    pass


def rollback_to_checkpoint(
    cwd: str,
    target_timestamp: float,
    session_file: str,
) -> tuple[list[str], list[str]]:
    """Rollback all checkpoints after *target_timestamp* for the given session.

    Only operates on checkpoints belonging to *session_file*.  The order is
    newest-first so that the final file state is correct when the same file
    was modified in multiple consecutive checkpoints.

    **Git hash check**: before any file is restored, the current git HEAD hash
    is compared against the hash stored in the checkpoint being rolled back.
    If they don't match the operation is aborted with ``RollbackError``.

    Args:
        cwd: Working directory.
        target_timestamp: Unix timestamp — only checkpoints newer than this
                          are rolled back.
        session_file: Only roll back checkpoints that belong to this session.

    Returns:
        ``(skipped, errors)`` — lists of file paths (rel to cwd) that were
        skipped (binary) or that failed to restore.

    Raises:
        RollbackError: If the current git HEAD hash doesn't match the first
                       (most recent) checkpoint's recorded hash.
    """
    mapping = _load_mapping(cwd)
    candidates: list[dict] = []
    remaining: list[dict] = []

    # Filter by session_file and target_timestamp
    for entry in mapping.get("mappings", []):
        if entry.get("session_file") != session_file:
            remaining.append(entry)
            continue
        cp_ts = _checkpoint_timestamp_to_unix(entry["timestamp"])
        if cp_ts > target_timestamp:
            candidates.append(entry)
        else:
            remaining.append(entry)

    # Sort newest first
    candidates.sort(key=lambda e: _checkpoint_timestamp_to_unix(e["timestamp"]), reverse=True)

    if not candidates:
        return [], []

    # ── Git hash check ────────────────────────────────────────────────
    current_hash = _get_git_head_hash(cwd)
    for entry in candidates:
        recorded_hash = entry.get("git_commit_hash", "")
        if recorded_hash and current_hash and current_hash != recorded_hash:
            raise RollbackError(
                f"Git HEAD hash mismatch: current={current_hash}, "
                f"expected={recorded_hash} (from checkpoint "
                f"{entry['checkpoint_filename']}). "
                f"Rollback rejected — new commits detected since snapshot."
            )

    # ── Apply rollback (newest first) ─────────────────────────────────
    resolved_cwd = str(Path(cwd).resolve())
    all_skipped: list[str] = []
    all_errors: list[str] = []

    for entry in candidates:
        cp = get_checkpoint(cwd, entry["checkpoint_filename"])
        if cp is None:
            all_errors.append(f"<checkpoint:{entry['checkpoint_filename']}> (unreadable)")
            continue

        files = cp.get("files", {})

        # modified: write saved (before) content back
        for rel_path, before_content in files.get("modified", {}).items():
            abs_path = os.path.normpath(os.path.join(resolved_cwd, rel_path))
            try:
                os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                Path(abs_path).write_text(before_content, encoding="utf-8")
            except (OSError, UnicodeEncodeError):
                all_errors.append(rel_path)

        # deleted: restore file with saved (before) content
        for rel_path, before_content in files.get("deleted", {}).items():
            abs_path = os.path.normpath(os.path.join(resolved_cwd, rel_path))
            try:
                os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                Path(abs_path).write_text(before_content, encoding="utf-8")
            except (OSError, UnicodeEncodeError):
                all_errors.append(rel_path)

        # added: delete the file that was created
        for rel_path in files.get("added", []):
            abs_path = os.path.normpath(os.path.join(resolved_cwd, rel_path))
            try:
                if os.path.isfile(abs_path):
                    os.remove(abs_path)
            except OSError:
                all_errors.append(rel_path)

        # binary: skip (same as before)
        for rel_path in files.get("binary", []):
            all_skipped.append(rel_path)

    # Remove rolled-back entries from mapping
    mapping["mappings"] = remaining
    _save_mapping(cwd, mapping)

    return all_skipped, all_errors


# ── Cleanup ────────────────────────────────────────────────────────────────


def cleanup_checkpoints(cwd: str, max_keep: int = _MAX_KEEP) -> int:
    """Remove excess checkpoints, keeping only the *max_keep* most recent ones.

    Checks are identified via the mapping file.  Older checkpoint files are
    deleted from disk and their mapping entries are removed.

    Returns the number of checkpoints deleted.
    """
    mapping = _load_mapping(cwd)
    entries = mapping.get("mappings", [])
    if len(entries) <= max_keep:
        return 0

    # Sort by timestamp (oldest first)
    entries.sort(key=lambda e: e.get("timestamp", ""))

    to_remove = entries[:-max_keep]  # oldest ones
    to_keep = entries[-max_keep:]    # most recent

    diff_dir = get_diff_dir(cwd)
    deleted_count = 0
    for entry in to_remove:
        filename = entry.get("checkpoint_filename", "")
        if filename:
            filepath = os.path.join(diff_dir, filename)
            try:
                if os.path.isfile(filepath):
                    os.remove(filepath)
                    deleted_count += 1
            except OSError:
                pass

    mapping["mappings"] = to_keep
    _save_mapping(cwd, mapping)

    return deleted_count
