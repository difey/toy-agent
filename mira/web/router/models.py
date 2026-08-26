"""共享数据模型：REST 请求体。

各路由模块从本模块导入所需请求体，避免重复定义。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CreateSessionBody(BaseModel):
    workspace: str
    agent_type: str = "main"
    model: str | None = None  # 模型串 {provider}/{model}（决策 #26：provider 由模型推导）


class ForkSessionBody(BaseModel):
    until_seq: int  # 分叉断点：把源会话 seq < until_seq 的对话复制为新 session 初始上下文


class SendMessageBody(BaseModel):
    content: str = Field(min_length=1)
    model: str  # 每回复模型串 {provider}/{model}（决策 #25/#26）
    effort: str | None = None  # reasoning 模型思考强度（low/medium/high）；off/None=不启用
    attachments: list[str] = Field(default_factory=list)  # 用户选中的文件绝对路径列表


class InsertMessageBody(BaseModel):
    content: str = Field(min_length=1)
    model: str
    effort: str | None = None
    interrupt: bool = False  # True=立即斧正（停止当前回复优先处理）；False=排队
    attachments: list[str] = Field(default_factory=list)  # 用户选中的文件绝对路径列表


class RenameWorkspaceBody(BaseModel):
    name: str = Field(min_length=1)


class ResolveApprovalBody(BaseModel):
    decision: str  # allow | deny | always


class AnswerQuestionBody(BaseModel):
    answer: str = Field(min_length=1)  # 用户回答（预设选项文本或自由输入）


class UpdateConfigBody(BaseModel):
    section: str  # general | providers | mcp | skills | agents
    data: dict
