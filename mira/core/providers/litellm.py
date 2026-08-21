"""LiteLLM Provider（决策 #24）：LLM 调用统一走 litellm。

- config.type = litellm provider 前缀（openai / anthropic / ollama / gemini / …）；
- stream_chat → litellm.completion(model=f"{type}/{model}", stream=True, reasoning_effort=effort)；
- 模型目录来自 ModelCatalog（models.dev 快照），不再直连 {base}/models；
- 流式 chunk 统一为 StreamChunk；OpenAI 风格 tool_calls 增量按 index 累加。
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from mira.core.providers.base import (
    ChatMessage,
    LLMProvider,
    ModelInfo,
    StreamChunk,
    Usage,
)
from mira.core.providers.catalog import ModelCatalog


class LiteLLMProvider(LLMProvider):
    def __init__(
        self,
        id: str,
        *,
        provider_type: str = "openai",
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_s: float = 120.0,
        catalog: ModelCatalog | None = None,
    ) -> None:
        self.id = id
        self.provider_type = provider_type
        self.base_url = base_url
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.catalog = catalog or ModelCatalog()
        # litellm provider 前缀：非 litellm 原生 provider 且配了 base_url 时按 OpenAI 兼容处理
        self._provider_prefix = self._resolve_provider_prefix(provider_type, base_url)

    @staticmethod
    def _resolve_provider_prefix(provider_type: str, base_url: str | None) -> str:
        """返回传给 litellm 的 provider 前缀。

        models.dev 里有些 provider（如 opencode-go，npm=@ai-sdk/openai-compatible）并非
        litellm 原生 provider；若配置了 base_url（OpenAI 兼容端点），回退用 openai 协议。
        """
        if provider_type == "mock":
            return "mock"
        try:
            from litellm import get_llm_provider  # 延迟导入：测试 / mock 场景不依赖

            get_llm_provider(f"{provider_type}/__probe__")
            return provider_type
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            unknown = (
                "LLM Provider NOT provided" in msg
                or "unknown provider" in msg.lower()
                or "not a valid provider" in msg.lower()
            )
            if unknown and base_url:
                return "openai"  # OpenAI 兼容端点
            return provider_type

    def _full_model(self, model: str | None) -> str:
        # 决策 #25：provider 不持有默认模型（model 由每回复 / agent 决定）；此处仅防空值
        m = model or "gpt-4o-mini"
        return m if "/" in m else f"{self._provider_prefix}/{m}"

    def list_models(self) -> list[ModelInfo]:
        """模型目录来自 models.dev（含 thinking_efforts）；无该供应商时返回空列表（无兜底模型）。"""
        models = self.catalog.models_for(self.provider_type)
        if models:
            return models
        return []

    def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        effort: str | None = None,
    ) -> Iterator[StreamChunk]:
        import litellm  # 延迟导入：仅在真实调用时加载（测试 / mock 场景不依赖）

        kwargs: dict[str, Any] = {
            "model": self._full_model(model),
            "messages": [m.to_api() for m in messages],
            "stream": True,
            "timeout": self.timeout_s,
            # 丢弃 provider 不支持的参数（如 openai 协议下的 reasoning_effort），
            # 否则 litellm 抛 UnsupportedParamsError
            "drop_params": True,
        }
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.base_url:
            kwargs["api_base"] = self.base_url
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if effort and effort != "off":
            kwargs["reasoning_effort"] = effort

        tool_calls: dict[int, dict[str, Any]] = {}
        usage: Usage | None = None
        finish: str | None = None
        for chunk in litellm.completion(**kwargs):  # type: ignore[union-attr]  # litellm stream 重载类型桩误报
            if chunk is None or not getattr(chunk, "choices", None):
                continue
            choice = chunk.choices[0]  # type: ignore[attr-defined]
            delta = getattr(choice, "delta", None)
            if delta is not None:
                text = getattr(delta, "content", None)
                reasoning = getattr(delta, "reasoning_content", None)
                if text or reasoning:
                    # DeepSeek thinking：reasoning_content 与 content 都在 delta 里
                    yield StreamChunk(text=text or "", reasoning_content=reasoning or "")
                for tc in getattr(delta, "tool_calls", None) or []:
                    idx = getattr(tc, "index", 0) or 0
                    slot = tool_calls.setdefault(
                        idx,
                        {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                    )
                    if getattr(tc, "id", None):
                        slot["id"] = tc.id
                    fn = getattr(tc, "function", None)
                    if fn is not None:
                        if getattr(fn, "name", None):
                            slot["function"]["name"] += fn.name
                        if getattr(fn, "arguments", None):
                            slot["function"]["arguments"] += fn.arguments
            if getattr(choice, "finish_reason", None):
                finish = choice.finish_reason
            u = getattr(chunk, "usage", None)
            if u is not None:
                usage = Usage(
                    input_tokens=getattr(u, "prompt_tokens", 0) or 0,
                    output_tokens=getattr(u, "completion_tokens", 0) or 0,
                    total_tokens=getattr(u, "total_tokens", 0) or 0,
                )
        tc_list = [tool_calls[i] for i in sorted(tool_calls)] or None
        yield StreamChunk(
            text="",
            done=True,
            finish_reason=finish or "stop",
            usage=usage or Usage(),
            tool_calls=tc_list,
        )
