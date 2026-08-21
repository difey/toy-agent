"""BackendAdapter：决定底层由谁真正跑 LLM 循环。

决策 #1：单一 pydantic-ai 后端，不做多框架切换。适配器收敛在本层，对上层透明；
若未来需替换框架，仅改此适配器。P0 采用 Provider 直连 HTTP 实现，pydantic-ai 适配器后置。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Mapping

from mira.core.config.schemas import ProviderConfig
from mira.core.providers.base import LLMProvider


class BackendAdapter(ABC):
    """框架后端适配器接口。"""

    name: str

    @abstractmethod
    def create_provider(
        self, cfg: ProviderConfig, env: Mapping[str, str] | None = None
    ) -> LLMProvider:
        """由配置构造一个 provider（可能包装底层框架的 Model/Agent）。"""
