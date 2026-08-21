"""SkillLoader：由配置构造注册表 + 组合 system prompt 指令。"""

from __future__ import annotations

from mira.core.config.schemas import SkillConfig
from mira.core.skills.base import Skill
from mira.core.skills.registry import SkillRegistry


class SkillLoader:
    @staticmethod
    def from_configs(configs: dict[str, SkillConfig]) -> SkillRegistry:
        return SkillRegistry().register_many(
            [
                Skill(
                    id=cfg.id,
                    name=cfg.name,
                    description=cfg.description,
                    prompt=cfg.prompt,
                    tools=cfg.tools,
                )
                for cfg in configs.values()
            ]
        )

    @staticmethod
    def compose_prompt(registry: SkillRegistry, enabled: list[str]) -> str:
        """把 agent 启用的技能指令拼进 system prompt（轻量注入）。"""
        parts: list[str] = []
        for skill_id in enabled:
            skill = registry.get(skill_id)
            if skill and skill.prompt:
                parts.append(skill.prompt)
        if not parts:
            return ""
        return "\n\n[技能指令]\n" + "\n\n".join(parts)
