"""Serialization helpers for converting core message objects to API-friendly dicts."""

from nano_claude.core.projections import build_timeline


def serialize_messages_for_api(messages) -> list[dict]:
    """Backward-compatible alias for the shared timeline projection."""
    return build_timeline(messages)
