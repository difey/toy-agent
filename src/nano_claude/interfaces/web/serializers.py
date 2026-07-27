"""Serialization helpers for converting core message objects to API-friendly dicts."""

import json

from nano_claude.core.message import AssistantMessage, DiffSummaryMessage, SystemMessage, ToolResult, UserMessage


def serialize_messages_for_api(messages) -> list[dict]:
    """Convert session messages to a format suitable for the web frontend."""
    result = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            result.append({
                "role": "system",
                "type": "system",
                "content": msg.content,
                "timestamp": msg.timestamp,
            })
        elif isinstance(msg, UserMessage):
            content = msg.content if isinstance(msg.content, str) else json.dumps(msg.content, ensure_ascii=False)
            result.append({
                "role": "user",
                "type": "text",
                "content": content,
                "timestamp": msg.timestamp,
            })
        elif isinstance(msg, AssistantMessage):
            if msg.content:
                result.append({
                    "role": "assistant",
                    "type": "text",
                    "content": msg.content,
                    "timestamp": msg.timestamp,
                })
            for tc in msg.tool_calls:
                result.append({
                    "role": "assistant",
                    "type": "tool_start",
                    "name": tc.name,
                    "arguments": tc.arguments,
                    "tool_call_id": tc.id,
                    "timestamp": msg.timestamp,
                })
        elif isinstance(msg, ToolResult):
            result.append({
                "role": "tool",
                "type": "tool_result",
                "name": msg.tool_name or "",
                "content": msg.content[:2000],
                "tool_call_id": msg.tool_call_id,
                "timestamp": msg.timestamp,
            })
        elif isinstance(msg, DiffSummaryMessage):
            result.append({
                "role": "diff_summary",
                "type": "diff_summary",
                "checkpoint_filename": msg.checkpoint_filename,
                "summary": msg.summary,
                "timestamp": msg.timestamp,
            })
    return result
