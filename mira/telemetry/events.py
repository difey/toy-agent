"""遥测事件 schema（Event Sourcing 统一信封）。

taxonomy 见 docs/data-models.md；信封字段：
  event_id / ts / session_id / span_id / parent_span_id / seq / type / payload
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from mira.util import utcnow_iso


class EventType(str, Enum):
    # 会话
    SESSION_CREATED = "session.created"
    SESSION_CLOSED = "session.closed"
    SESSION_STATUS = "session.status"
    SESSION_TITLED = "session.titled"
    SESSION_SYSTEM_PROMPT = "session.system_prompt"
    # 消息
    USER_MESSAGE = "user.message"
    AGENT_MESSAGE = "agent.message"
    AGENT_MESSAGE_DELTA = "agent.message.delta"
    # LLM
    LLM_REQUEST = "llm.request"
    LLM_STREAM_CHUNK = "llm.stream_chunk"
    LLM_RESPONSE = "llm.response"
    # 工具
    TOOL_CALL = "tool.call"
    TOOL_RESULT = "tool.result"
    TOOL_ERROR = "tool.error"
    # Agent
    AGENT_LOOP_START = "agent.loop.start"
    AGENT_LOOP_END = "agent.loop.end"
    AGENT_SPAWN = "agent.spawn"
    AGENT_JOIN = "agent.join"
    AGENT_REPORT = "agent.report"
    # 任务分派
    TASK_DISPATCH = "task.dispatch"
    TASK_START = "task.start"
    TASK_COMPLETE = "task.complete"
    TASK_FAILED = "task.failed"
    # 技能
    SKILL_USED = "skill.used"
    # 审批（HITL）
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_RESOLVED = "approval.resolved"
    # 错误 / 指标
    ERROR_RAISED = "error.raised"
    METRIC_SNAPSHOT = "metric.snapshot"


class Event(BaseModel):
    """统一事件信封。一次 agent 运行 = 一棵带 span 上下文的事件树。"""

    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    ts: str = Field(default_factory=utcnow_iso)
    session_id: str = ""
    span_id: str | None = None
    parent_span_id: str | None = None
    seq: int = 0
    type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> str:
        return self.model_dump_json()
