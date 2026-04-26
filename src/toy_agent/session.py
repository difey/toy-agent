import json
from pathlib import Path

from toy_agent.message import (
    AssistantMessage,
    Message,
    SystemMessage,
    ToolCall,
    ToolResult,
    UserMessage,
)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def message_tokens(msg: Message) -> int:
    if isinstance(msg, SystemMessage):
        return estimate_tokens(msg.content)
    elif isinstance(msg, UserMessage):
        if isinstance(msg.content, str):
            return estimate_tokens(msg.content)
        return estimate_tokens(json.dumps(msg.content))
    elif isinstance(msg, AssistantMessage):
        n = estimate_tokens(msg.content or "")
        for tc in msg.tool_calls:
            n += estimate_tokens(json.dumps(tc.arguments)) + 4
        return n
    elif isinstance(msg, ToolResult):
        return estimate_tokens(msg.content)
    return 0


class Session:
    def __init__(self, system_prompt: str = "", max_tokens: int = 100_000):
        self.max_tokens = max_tokens
        self.messages: list[Message] = []
        if system_prompt:
            self.messages.append(SystemMessage(content=system_prompt))

    def add_user_message(self, content: str) -> None:
        self.messages.append(UserMessage(content=content))
        self._compact()

    def add_message(self, msg: Message) -> None:
        self.messages.append(msg)
        self._compact()

    def total_tokens(self) -> int:
        return sum(message_tokens(m) for m in self.messages)

    def _compact(self) -> None:
        while self.total_tokens() > self.max_tokens and len(self.messages) > 1:
            if not self._remove_oldest_turn():
                break

    def _remove_oldest_turn(self) -> bool:
        user_indices = [
            i for i in range(len(self.messages))
            if isinstance(self.messages[i], UserMessage)
        ]
        if len(user_indices) < 2:
            return False
        first = user_indices[0]
        end = user_indices[1] - 1
        for _ in range(first, end + 1):
            self.messages.pop(first)
        return True

    def save(self, path: str) -> None:
        data = {
            "max_tokens": self.max_tokens,
            "messages": [
                {
                    "type": type(m).__name__,
                    "data": _serialize_message(m),
                }
                for m in self.messages
            ],
        }
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2))

    @classmethod
    def load(cls, path: str) -> "Session":
        data = json.loads(Path(path).read_text())
        session = cls(max_tokens=data.get("max_tokens", 100_000))
        session.messages = [_deserialize_message(item) for item in data["messages"]]
        return session


def _serialize_message(msg: Message) -> dict:
    if isinstance(msg, SystemMessage):
        return {"content": msg.content}
    elif isinstance(msg, UserMessage):
        return {"content": msg.content}
    elif isinstance(msg, AssistantMessage):
        data: dict = {
            "content": msg.content,
            "tool_calls": [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in msg.tool_calls
            ],
        }
        if msg.reasoning_content:
            data["reasoning_content"] = msg.reasoning_content
        return data
    elif isinstance(msg, ToolResult):
        return {
            "tool_call_id": msg.tool_call_id,
            "content": msg.content,
        }
    raise TypeError(f"Unknown message type: {type(msg)}")


def _deserialize_message(item: dict) -> Message:
    msg_type = item["type"]
    data = item["data"]
    if msg_type == "SystemMessage":
        return SystemMessage(content=data["content"])
    elif msg_type == "UserMessage":
        return UserMessage(content=data["content"])
    elif msg_type == "AssistantMessage":
        return AssistantMessage(
            content=data.get("content"),
            reasoning_content=data.get("reasoning_content"),
            tool_calls=[
                ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
                for tc in data.get("tool_calls", [])
            ],
        )
    elif msg_type == "ToolResult":
        return ToolResult(
            tool_call_id=data["tool_call_id"],
            content=data["content"],
        )
    raise TypeError(f"Unknown message type: {msg_type}")
