import json
from typing import AsyncIterator

from openai import AsyncOpenAI

from nano_claude.message import (
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


def _get_reasoning(obj) -> str:
    if hasattr(obj, "reasoning_content") and obj.reasoning_content:
        return obj.reasoning_content
    if hasattr(obj, "model_extra"):
        extra = obj.model_extra or {}
        return extra.get("reasoning_content", "") or ""
    return ""


class LLMClient:
    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    async def chat(
        self,
        messages: list[Message],
        tools: list[dict],
    ) -> AssistantMessage:
        formatted = self._format_messages(messages)
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=formatted,
            tools=tools,
            tool_choice="auto",
            temperature=0.0,
        )
        choice = response.choices[0]
        reasoning = _get_reasoning(choice.message)
        return AssistantMessage(
            content=choice.message.content,
            reasoning_content=reasoning,
            tool_calls=[
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments),
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
        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=formatted,
            tools=tools,
            tool_choice="auto",
            temperature=0.0,
            stream=True,
            stream_options={"include_usage": False},
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
