from dataclasses import dataclass, field
from typing import Literal


@dataclass
class SystemMessage:
    role: Literal["system"] = "system"
    content: str = ""


@dataclass
class UserMessage:
    content: str | list[dict]
    role: Literal["user"] = "user"


@dataclass
class AssistantMessage:
    role: Literal["assistant"] = "assistant"
    content: str | None = None
    reasoning_content: str = ""
    tool_calls: list["ToolCall"] = field(default_factory=list)


@dataclass
class ToolResult:
    role: Literal["tool"] = "tool"
    tool_call_id: str = ""
    content: str = ""
    tool_name: str = ""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


Message = SystemMessage | UserMessage | AssistantMessage | ToolResult


@dataclass
class TextDelta:
    text: str


@dataclass
class ToolCallBegin:
    index: int
    id: str
    name: str


@dataclass
class ToolCallArgDelta:
    index: int
    arguments: str


@dataclass
class ReasoningDelta:
    text: str


StreamChunk = TextDelta | ToolCallBegin | ToolCallArgDelta | ReasoningDelta
