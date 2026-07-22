import json
from typing import AsyncIterator

import litellm

from nano_claude.core.message import (
    AssistantMessage,
    Message,
    ReasoningDelta,
    StreamChunk,
    SystemMessage,
    TextDelta,
    ToolCall,
    ToolCallArgDelta,
    ToolCallBegin,
    ToolResult,
    UserMessage,
)

# litellm mirrors provider quirks (e.g. thinking-model reasoning traces) as
# extra/unsupported params. Drop them instead of raising so any provider it
# supports "just works" without per-provider special-casing here.
litellm.drop_params = True


def _get_reasoning(obj) -> str:
    if hasattr(obj, "reasoning_content") and obj.reasoning_content:
        return obj.reasoning_content
    if hasattr(obj, "model_extra"):
        extra = obj.model_extra or {}
        return extra.get("reasoning_content", "") or ""
    return ""


class LLMClient:
    """Unified multi-provider LLM client built on top of the litellm SDK.

    litellm dispatches `model` (optionally provider-prefixed, e.g.
    "anthropic/claude-3-5-sonnet") to the right provider backend and
    normalizes the request/response shape to the OpenAI chat completions
    format, so provider-specific handling no longer needs to live here.
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 60.0,
        max_retries: int = 2,
    ):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries

    def _completion_kwargs(self, formatted: list[dict], tools: list[dict], **extra) -> dict:
        kwargs: dict = dict(
            model=self.model,
            messages=formatted,
            tools=tools,
            tool_choice="auto",
            temperature=0.0,
            api_key=self.api_key,
            timeout=self.timeout,
            num_retries=self.max_retries,
            **extra,
        )
        if self.base_url:
            # Custom endpoints (self-hosted proxies, Ollama, OpenAI-compatible
            # gateways, etc.) are addressed as OpenAI-compatible chat
            # completions APIs.
            kwargs["api_base"] = self.base_url
            kwargs["custom_llm_provider"] = "openai"
        return kwargs

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict],
    ) -> AssistantMessage:
        formatted = self._format_messages(messages)
        response = await litellm.acompletion(**self._completion_kwargs(formatted, tools))
        choice = response.choices[0]
        reasoning = _get_reasoning(choice.message)
        return AssistantMessage(
            content=choice.message.content,
            reasoning_content=reasoning,
            tool_calls=[
                ToolCall(
                    id=tc.id,
                    name=tc.function.name, # type: ignore
                    arguments=json.loads(tc.function.arguments), # type: ignore
                )
                for tc in (choice.message.tool_calls or [])
            ],
        )

    async def chat_stream(
        self,
        messages: list[Message],
        tools: list[dict],
    ) -> AsyncIterator[StreamChunk]:
        formatted = self._format_messages(messages)
        stream = await litellm.acompletion(
            **self._completion_kwargs(
                formatted,
                tools,
                stream=True,
                stream_options={"include_usage": False},
            )
        )
        async for event in stream:
            delta = event.choices[0].delta if event.choices else None
            if delta is None:
                continue
            reasoning = _get_reasoning(delta)
            if reasoning:
                yield ReasoningDelta(text=reasoning)
            if delta.content:
                yield TextDelta(text=delta.content)
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    if tc_delta.id and tc_delta.function and tc_delta.function.name:
                        yield ToolCallBegin(
                            index=tc_delta.index,
                            id=tc_delta.id,
                            name=tc_delta.function.name,
                        )
                    elif tc_delta.function and tc_delta.function.arguments:
                        yield ToolCallArgDelta(
                            index=tc_delta.index,
                            arguments=tc_delta.function.arguments,
                        )

    def _format_messages(self, messages: list[Message]) -> list[dict]:
        formatted = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                formatted.append({"role": "system", "content": msg.content})
            elif isinstance(msg, UserMessage):
                formatted.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AssistantMessage):
                entry: dict = {"role": "assistant"}
                if msg.content is not None:
                    entry["content"] = msg.content
                # DeepSeek thinking mode requires reasoning_content to be passed
                # back for previous assistant turns. OpenAI/Anthropic simply
                # ignore this field, so including it is harmless.
                if msg.reasoning_content is not None:
                    entry["reasoning_content"] = msg.reasoning_content
                if msg.tool_calls:
                    entry["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                formatted.append(entry)
            elif isinstance(msg, ToolResult):
                formatted.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": msg.content,
                })
        return formatted
