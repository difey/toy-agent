"""统一契约：核心数据模型（Session / Message / ToolCall / SkillUse / TaskSpec / AgentReport）。

字段口径见 docs/data-models.md。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from mira.util import new_id, new_session_id, utcnow_iso


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class SessionStatus(str, Enum):
    RUNNING = "running"
    IDLE = "idle"
    WAITING = "waiting"  # 等待审批（HITL）
    FAILED = "failed"


class ToolCallStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    ERROR = "error"


class SkillUseMode(str, Enum):
    PROMPT = "prompt"  # 指令注入 system prompt
    TOOL = "tool"  # 作为 use_skill 工具按需加载


class ReportStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Session(BaseModel):
    """一个会话 = 一个工作区 + 一个工作 agent，是执行与遥测的基本单位。"""

    id: str = Field(default_factory=new_session_id)  # id = hashcode
    workspace: str = ""
    agent_type: str = "main"
    model: str = ""  # 模型串 {provider}/{model}（决策 #26：provider 由模型推导，不单独存储）
    title: str = ""  # 会话标题：首轮结束后由配置式 agent（summarizer）总结生成
    created_at: str = Field(default_factory=utcnow_iso)
    updated_at: str = ""  # 最近交互时间（新对话/回复/查看）；会话列表按此倒序
    closed_at: str | None = None
    status: SessionStatus = SessionStatus.IDLE
    meta: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    """会话消息（对话历史中的一条）。"""

    id: str = Field(default_factory=lambda: new_id("msg"))
    session_id: str = ""
    role: MessageRole
    content: str = ""
    created_at: str = Field(default_factory=utcnow_iso)
    seq: int = 0


class ToolCall(BaseModel):
    """一次工具调用（含参数 / 结果 / 状态 / 耗时）。"""

    id: str = Field(default_factory=lambda: new_id("tc"))
    message_id: str = ""
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: str | None = None
    status: ToolCallStatus = ToolCallStatus.PENDING
    duration_ms: float | None = None
    cost: float = 0.0


class SkillUse(BaseModel):
    """一次技能使用记录。"""

    skill_name: str
    mode: SkillUseMode = SkillUseMode.PROMPT
    params: dict[str, Any] = Field(default_factory=dict)
    result_summary: str | None = None


class TaskSpec(BaseModel):
    """分派契约：主 agent 通过 dispatch_task 下发的子任务描述。"""

    task_id: str = Field(default_factory=lambda: new_id("task"))
    target_agent: str
    goal: str = ""
    instructions: str = ""
    context: list[str] = Field(default_factory=list)  # 文件路径 / 文档 URL / 中间结论引用
    images: list[str] = Field(default_factory=list)  # 图片绝对路径（视觉 agent 查看用）
    input_payload: dict[str, Any] = Field(default_factory=dict)
    report_schema: str | None = None
    expected_output: str | None = None


class AgentReport(BaseModel):
    """汇报契约：子 agent 结构化汇报（格式不强制，重点是信息充分性，决策 #9）。"""

    task_id: str
    agent_id: str
    status: ReportStatus = ReportStatus.SUCCEEDED
    summary: str = ""
    findings: list[str] = Field(default_factory=list)
    recommendation: str = ""
    artifacts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    report_path: str | None = None  # 完整报告落盘路径（决策 #7）
