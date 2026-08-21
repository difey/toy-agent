"""AgentRegistry：扫描配置目录加载所有 agent 定义，配置即注册。"""

from __future__ import annotations

from mira.core.agents.base import BaseAgent
from mira.core.config.schemas import AgentConfig
from mira.core.config.store import ConfigStore
from mira.core.skills.registry import SkillRegistry


class AgentRegistry:
    def __init__(
        self,
        agents: dict[str, AgentConfig],
        skills: SkillRegistry | None = None,
    ) -> None:
        self._agents: dict[str, BaseAgent] = {
            aid: BaseAgent(cfg) for aid, cfg in agents.items()
        }
        self._skills = skills

    @classmethod
    def from_store(
        cls, store: ConfigStore, skills: SkillRegistry | None = None
    ) -> "AgentRegistry":
        return cls(store.agents(), skills)

    def get(self, agent_id: str) -> BaseAgent:
        try:
            return self._agents[agent_id]
        except KeyError:
            raise KeyError(f"未注册的 agent: {agent_id!r}") from None

    def has(self, agent_id: str) -> bool:
        return agent_id in self._agents

    def list(self) -> list[BaseAgent]:
        return list(self._agents.values())

    def ids(self) -> list[str]:
        return sorted(self._agents)
