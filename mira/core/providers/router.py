"""ProviderRouter：按 provider id 路由、重试（退避）、构建 provider 实例。

所有往返都经 Tracer 产出 llm.* 事件（P1 由 AgentRuntime 埋点）。
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Iterator
from typing import Any

from mira.core.config.schemas import ProviderConfig
from mira.core.providers.base import (
    ChatMessage,
    LLMProvider,
    ModelInfo,
    ModelResponse,
    StreamChunk,
    Usage,
)
from mira.core.providers.litellm import LiteLLMProvider
from mira.core.providers.mock import MockProvider


def build_provider(cfg: ProviderConfig) -> LLMProvider:
    """由 ProviderConfig 构造 provider 实例。

    type=mock → MockProvider（本地可测 / 无 LLM 环境）；其余 type = litellm provider
    前缀（openai / anthropic / ollama / gemini / …），统一走 LiteLLMProvider。
    api_key 为明文（决策 #8a；已取消 env 引用设计）。
    """
    if cfg.type == "mock":
        return MockProvider(id=cfg.id)
    return LiteLLMProvider(
        id=cfg.id,
        provider_type=cfg.type,
        base_url=cfg.base_url,
        api_key=cfg.api_key,
        timeout_s=cfg.timeout_s,
    )


def _consume(stream: Iterator[StreamChunk]) -> ModelResponse:
    buf: list[str] = []
    usage = Usage()
    finish: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    for chunk in stream:
        buf.append(chunk.text)
        if chunk.usage:
            usage = chunk.usage
        if chunk.tool_calls:
            tool_calls = chunk.tool_calls
        if chunk.done:
            finish = chunk.finish_reason or finish
    return ModelResponse(
        content="".join(buf), finish_reason=finish, usage=usage, tool_calls=tool_calls
    )


class ProviderRouter:
    """路由 / 重试（指数退避）/ 成本记账（基于 usage 响应）。"""

    def __init__(
        self,
        providers: Iterable[LLMProvider],
        *,
        max_retries: dict[str, int] | None = None,
    ) -> None:
        self._by_id: dict[str, LLMProvider] = {p.id: p for p in providers}
        self._max_retries = max_retries or {}

    @classmethod
    def from_configs(cls, configs: Iterable[ProviderConfig]) -> "ProviderRouter":
        configs = list(configs)
        return cls(
            [build_provider(c) for c in configs],
            max_retries={c.id: c.max_retries for c in configs},
        )

    def get(self, provider_id: str) -> LLMProvider:
        try:
            return self._by_id[provider_id]
        except KeyError:
            raise KeyError(f"未注册的 provider: {provider_id!r}") from None

    def available_models(self, provider_id: str | None = None) -> list[ModelInfo]:
        """聚合可用模型（含 thinking 能力）；缺省聚合全部 provider。失败逐个跳过。"""
        ids = [provider_id] if provider_id else list(self._by_id)
        out: dict[str, ModelInfo] = {}
        for pid in ids:
            provider = self._by_id.get(pid)
            if not provider:
                continue
            try:
                for m in provider.list_models():
                    cur = out.get(m.id)
                    if cur is None:
                        out[m.id] = m
                    elif m.supports_thinking and not cur.supports_thinking:
                        out[m.id] = m.model_copy(update={"supports_thinking": True})
            except Exception:  # noqa: BLE001
                continue
        return list(out.values())

    def stream_chat(
        self,
        provider_id: str,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        effort: str | None = None,
        max_retries: int | None = None,
        **kwargs: Any,
    ) -> Iterator[StreamChunk]:
        """路由到 provider 并流式调用（含重试退避）。

        model / effort：请求的关键参数，显式列出（其余 temperature/max_tokens/tools 等经 kwargs 透传）。
        """
        provider = self.get(provider_id)
        allowed = max_retries if max_retries is not None else self._max_retries.get(provider_id, 2)
        attempt = 0
        while True:
            try:
                yield from provider.stream_chat(messages, model=model, effort=effort, **kwargs)
                return
            except Exception as exc:
                attempt += 1
                if attempt > allowed:
                    raise
                time.sleep(min(0.5 * (2 ** attempt), 4.0))
                continue

    def chat(
        self,
        provider_id: str,
        messages: list[ChatMessage],
        **kwargs: Any,
    ) -> ModelResponse:
        return _consume(self.stream_chat(provider_id, messages, **kwargs))
