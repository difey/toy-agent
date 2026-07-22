"""Plan-document service — plan docs + modified-file metadata for the web UI."""

import os
import subprocess
from pathlib import Path

from nano_claude.infra.session import get_session_dir


def _latest_plan_file(cwd: str) -> Path | None:
    session_dir = Path(get_session_dir(cwd))
    if not session_dir.is_dir():
        return None
    md_files = sorted(session_dir.glob("*.md"), key=lambda f: os.path.getmtime(f))
    if not md_files:
        return None
    return md_files[-1]


def _list_plan_files(cwd: str) -> list[Path]:
    session_dir = Path(get_session_dir(cwd))
    if not session_dir.is_dir():
        return []
    files = [*session_dir.glob("*.md"), *session_dir.glob("*.md.resolved")]
    return sorted(files, key=lambda f: os.path.getmtime(f), reverse=True)


def list_plan_docs(cwd: str) -> list[dict]:
    """Return all plan documents in reverse chronological order."""
    return [
        {
            "filename": doc.name,
            "modified": os.path.getmtime(doc),
            "size": doc.stat().st_size,
        }
        for doc in _list_plan_files(cwd)
    ]


def _resolve_requested_plan(cwd: str, filename: str | None) -> Path | None:
    if not filename:
        latest = _latest_plan_file(cwd)
        if latest is not None:
            return latest
        all_docs = _list_plan_files(cwd)
        return all_docs[0] if all_docs else None

    for doc in _list_plan_files(cwd):
        if doc.name == filename:
            return doc
    return None


def get_plan_doc(cwd: str, filename: str | None = None) -> dict:
    """Return a selected plan document from the session directory."""
    target = _resolve_requested_plan(cwd, filename)
    if target is None:
        return {"exists": False, "filename": filename, "content": None, "modified": None, "size": None}
    return {
        "exists": True,
        "filename": target.name,
        "content": target.read_text(encoding="utf-8"),
        "modified": os.path.getmtime(target),
        "size": target.stat().st_size,
    }


def resolve_latest_plan(cwd: str) -> None:
    """Rename the latest .md file in the session directory to .md.resolved."""
    latest = _latest_plan_file(cwd)
    if latest is None:
        return
    latest_str = str(latest)
    resolved_path = latest_str + ".resolved"
    if os.path.exists(latest_str):
        os.rename(latest_str, resolved_path)


def list_modified_files(cwd: str) -> list[dict]:
    """Return modified/untracked files from git status for the current workspace."""
    try:
        root_proc = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        repo_root = root_proc.stdout.strip() or cwd
        status_proc = subprocess.run(
            ["git", "-C", repo_root, "status", "--short", "--untracked-files=all"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []

    modified_files: list[dict] = []
    for line in status_proc.stdout.splitlines():
        if len(line) < 4:
            continue
        code = line[:2]
        raw_path = line[3:]
        path = raw_path.split(" -> ", 1)[-1]
        status_code = code[1] if code[1] != " " else code[0]
        modified_files.append({
            "path": path,
            "status": status_code.strip() or "?",
        })
    return modified_files


def get_workspace_panel(cwd: str) -> dict:
    """Return the right-panel data for the main chat page."""
    return {
        "plan_docs": list_plan_docs(cwd),
        "modified_files": list_modified_files(cwd),
    }
