"""SkillRegistry：注册 / 查找 / 枚举。"""

from __future__ import annotations

from mira.core.skills.base import Skill


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> "SkillRegistry":
        self._skills[skill.id] = skill
        return self

    def register_many(self, skills: list[Skill]) -> "SkillRegistry":
        for s in skills:
            self.register(s)
        return self

    def get(self, skill_id: str) -> Skill | None:
        return self._skills.get(skill_id)

    def has(self, skill_id: str) -> bool:
        return skill_id in self._skills

    def names(self) -> list[str]:
        return sorted(self._skills)

    def list(self) -> list[Skill]:
        return list(self._skills.values())
