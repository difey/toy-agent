"""Mock Provider：本地可测、无网络依赖，供演示 / 测试 / 无 LLM 环境使用。

P1 起支持 tools 参数触发工具调用，用于驱动工具循环的测试。
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from mira.core.providers.base import (
    ChatMessage,
    ChatRole,
    LLMProvider,
    ModelInfo,
    StreamChunk,
    Usage,
)
from mira.util import count_tokens

MOCK_MODEL = ModelInfo(id="mock-model", name="mock-model", supports_thinking=False)


class MockProvider(LLMProvider):
    """确定性 mock：流式输出固定（或回显用户消息）文本，末片带 usage。

    支持 tool_calls：若配置且历史中尚无工具结果（role=tool），首轮返回工具调用
    以驱动工具循环；工具结果回填后返回普通回复。
    """

    def __init__(
        self,
        id: str = "mock",
        *,
        reply: str | None = None,
        chunk_size: int = 12,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_calls_once: bool = False,
        reasoning: str | None = None,  # DeepSeek thinking 推理链（先在流中输出，测试多轮保留）
    ) -> None:
        self.id = id
        self.reply = reply
        self.chunk_size = max(1, chunk_size)
        self.tool_calls = list(tool_calls or [])
        self.tool_calls_once = tool_calls_once  # P3：整场只触发一次工具调用（编排演示用）
        self._fired = False
        self.reasoning = reasoning

    def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        effort: str | None = None,  # mock 不关心 thinking effort
    ) -> Iterator[StreamChunk]:
        has_tool_result = any(m.role == ChatRole.TOOL for m in messages)
        emit_tools = bool(self.tool_calls and not has_tool_result)
        if self.tool_calls_once and self._fired:
            emit_tools = False  # P3：编排场景下，子 agent 复用同一 provider 时不再重复触发
        if emit_tools:
            # 首轮：只返回工具调用，触发工具循环
            self._fired = True
            inp = count_tokens("".join(m.content for m in messages))
            usage = Usage(
                input_tokens=inp, output_tokens=2, total_tokens=inp + 2, cost_usd=0.0
            )
            yield StreamChunk(
                text="",
                done=True,
                finish_reason="tool_calls",
                usage=usage,
                tool_calls=[dict(tc) for tc in self.tool_calls],
            )
            return

        user = next(
            (m.content for m in reversed(messages) if m.role == ChatRole.USER), ""
        )
        if self.reply is not None:
            reply = self.reply
        elif user:
            reply = f"[mock:{self.id}] 收到：{user[:64]}"
        else:
            reply = f"[mock:{self.id}] 骨架演示：这是来自 mock provider 的流式回复。"
        if max_tokens:
            reply = reply[: max(1, max_tokens)]

        if self.reasoning:
            for i in range(0, len(self.reasoning), self.chunk_size):
                yield StreamChunk(reasoning_content=self.reasoning[i : i + self.chunk_size])
        for i in range(0, len(reply), self.chunk_size):
            yield StreamChunk(text=reply[i : i + self.chunk_size])

        inp = count_tokens("".join(m.content for m in messages))
        out = count_tokens(reply)
        usage = Usage(
            input_tokens=inp,
            output_tokens=out,
            total_tokens=inp + out,
            cost_usd=round(0.0001 * out, 6),
        )
        yield StreamChunk(text="", done=True, finish_reason="stop", usage=usage)

    def list_models(self) -> list[ModelInfo]:
        """mock 只提供一个复读模型。"""
        return [MOCK_MODEL.model_copy()]
