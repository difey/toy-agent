"""Plan-document service — reads/resolves the latest plan markdown in the session dir."""

import os
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


def get_plan_doc(cwd: str) -> dict:
    """Return the latest plan document from the session directory."""
    latest = _latest_plan_file(cwd)
    if latest is None:
        return {"exists": False, "filename": None, "content": None, "modified": None}
    return {
        "exists": True,
        "filename": latest.name,
        "content": latest.read_text(encoding="utf-8"),
        "modified": os.path.getmtime(latest),
        "size": latest.stat().st_size,
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
