"""BaseAgent：由 AgentConfig 生成的运行时实例。

运行时只实现「如何执行配置」；agent 的「是什么」完全由配置决定（system prompt + skills + tools + mcp）。
"""

from __future__ import annotations

from mira.core.config.schemas import AgentConfig
from mira.core.skills.loader import SkillLoader
from mira.core.skills.registry import SkillRegistry


class BaseAgent:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config

    @property
    def id(self) -> str:
        return self.config.id

    @property
    def role(self) -> str:
        return self.config.role.value

    @property
    def name(self) -> str:
        return self.config.name or self.config.id

    @property
    def model(self) -> str | None:
        return self.config.model

    @property
    def effort(self) -> str | None:
        return self.config.effort

    def enabled_tools(self) -> list[str]:
        return list(self.config.tools.enabled)

    def enabled_skills(self) -> list[str]:
        return list(self.config.skills.enabled)

    def enabled_mcp(self) -> list[str]:
        return list(self.config.mcp.enabled)

    def compose_system_prompt(self, skills: SkillRegistry | None = None) -> str:
        """system prompt + 启用技能的指令注入。"""
        prompt = self.config.system_prompt
        if skills:
            extra = SkillLoader.compose_prompt(skills, self.enabled_skills())
            if extra:
                prompt = (prompt + extra).strip()
        return prompt
