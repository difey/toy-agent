"""Skill 数据模型：元数据 + SKILL.md 指令（此处为指令文本，SKILL.md 文件加载在后续）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Skill(BaseModel):
    id: str
    name: str = ""
    description: str = ""
    prompt: str = ""  # 指令文本（注入 system prompt 或作为 use_skill 内容）
    tools: list[str] = Field(default_factory=list)  # 依赖工具
