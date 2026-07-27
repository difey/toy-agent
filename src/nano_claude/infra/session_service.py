"""Shared session lifecycle helpers used by front ends.

Centralizes the "resume the most recent session for a cwd, or start a new
one" logic so front ends don't each re-implement it.
"""

from nano_claude.infra.session import Session, list_sessions, session_path


def resume_or_create_session(cwd: str) -> tuple[Session, str]:
    """Load the most recent session for `cwd`, or create a new one.

    Returns a tuple of (session, session_file_path).
    """
    existing = list_sessions(cwd)
    if existing:
        last_path = existing[-1]  # sorted, so the last entry is the most recent
        try:
            return Session.load(last_path), last_path
        except Exception:
            pass
    return Session(), session_path(cwd)
