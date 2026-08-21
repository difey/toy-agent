"""pydantic-ai 后端适配器（占位）。

决策 #1 收敛点：P1+ 将循环委托给 pydantic-ai 的 Model/Tool 能力并透传事件。
当前阶段采用 Provider 直连 HTTP 实现（core/providers/openai.py / mock.py）。
"""

from __future__ import annotations

from typing import Mapping

from mira.core.config.schemas import ProviderConfig
from mira.core.providers.base import LLMProvider
from mira.core.providers.framework.base import BackendAdapter


class PydanticAIAdapter(BackendAdapter):
    name = "pydantic-ai"

    def create_provider(
        self, cfg: ProviderConfig, env: Mapping[str, str] | None = None
    ) -> LLMProvider:
        raise NotImplementedError(
            "pydantic-ai 后端适配在 P1+ 接入；当前使用 Provider 直连 HTTP 实现。"
        )
