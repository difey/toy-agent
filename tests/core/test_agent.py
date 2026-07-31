from unittest.mock import patch

import pytest

from nano_claude.core.agent import Agent
from nano_claude.core.message import AssistantMessage, TextDelta, ToolCall, ToolCallBegin, ToolCallArgDelta
from nano_claude.core.session import Session
from nano_claude.core.tool_contracts import AgentCallbacks, ToolContext
from nano_claude.core.tool_registry import ToolRegistry
from nano_claude.tools import BashTool, WriteTool


def test_registry_to_openai_tools():
    registry = ToolRegistry()
    registry.register(BashTool())
    registry.register(WriteTool())

    tools = registry.to_openai_tools()
    assert len(tools) == 2
    assert tools[0]["type"] == "function"
    assert {t["function"]["name"] for t in tools} == {"bash", "write"}


def test_registry_get():
    registry = ToolRegistry()
    registry.register(BashTool())
    assert registry.get("bash") is not None
    assert registry.get("nonexistent") is None


@pytest.mark.asyncio
async def test_agent_simple_reply():
    registry = ToolRegistry()
    agent = Agent(model="gpt-4o", tools=registry, api_key="test-key")

    with patch.object(agent.llm, "chat") as mock_chat:
        mock_chat.return_value = AssistantMessage(
            content="Hello! How can I help?",
            tool_calls=[],
        )

        result = await agent.run("hello", "/tmp")
        assert "Hello" in result
        assert mock_chat.await_count >= 1  # may be called by summarizer too


@pytest.mark.asyncio
async def test_agent_with_tool_call():
    registry = ToolRegistry()
    registry.register(WriteTool())
    agent = Agent(model="gpt-4o", tools=registry, api_key="test-key")

    with patch.object(agent.llm, "chat") as mock_chat:
        mock_chat.side_effect = [
            AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="write",
                        arguments={
                            "filePath": "/tmp/test_hello.py",
                            "content": "print('hello')",
                        },
                    )
                ],
            ),
            AssistantMessage(
                content="Done! Created test_hello.py.",
                tool_calls=[],
            ),
        ]

        result = await agent.run("write hello world", "/tmp")
        assert "Done" in result
        assert mock_chat.await_count == 2


def _async_gen(items):
    async def gen():
        for item in items:
            yield item
    return gen()


@pytest.mark.asyncio
async def test_agent_stream_simple_reply():
    registry = ToolRegistry()
    collected_text = []
    agent = Agent(
        model="gpt-4o",
        tools=registry,
        api_key="test-key",
        callbacks=AgentCallbacks(on_text_delta=lambda t: collected_text.append(t)),
    )

    with patch.object(agent.llm, "chat_stream") as mock_stream:
        mock_stream.return_value = _async_gen([
            TextDelta(text="Hello"),
            TextDelta(text=" world!"),
        ])

        await agent.run_stream("hello", "/tmp")
        assert "".join(collected_text) == "Hello world!"


@pytest.mark.asyncio
async def test_agent_stream_with_tool_call():
    registry = ToolRegistry()
    registry.register(WriteTool())
    collected_text = []
    tool_starts = []
    tool_ends = []

    agent = Agent(
        model="gpt-4o",
        tools=registry,
        api_key="test-key",
        callbacks=AgentCallbacks(
            on_text_delta=lambda t: collected_text.append(t),
            on_tool_start=lambda tc: tool_starts.append(tc.name),
            on_tool_end=lambda n, t, o, *_: tool_ends.append((n, t)),
        ),
    )

    with patch.object(agent.llm, "chat_stream") as mock_stream:
        mock_stream.side_effect = [
            _async_gen([
                TextDelta(text="Let me write that file."),
                ToolCallBegin(index=0, id="call_1", name="write"),
                ToolCallArgDelta(index=0, arguments='{"filePath": "/tmp/test.py", "content": "print(1)"}'),
            ]),
            _async_gen([
                TextDelta(text="Done! File created."),
            ]),
        ]

        await agent.run_stream("create a test file", "/tmp")
        assert "Let me write that file." in "".join(collected_text)
        assert "Done! File created." in "".join(collected_text)
        assert "write" in tool_starts
        assert any(t[0] == "write" for t in tool_ends)


@pytest.mark.asyncio
async def test_agent_stream_unknown_tool():
    registry = ToolRegistry()
    tool_ends = []

    agent = Agent(
        model="gpt-4o",
        tools=registry,
        api_key="test-key",
        callbacks=AgentCallbacks(
            on_tool_end=lambda n, t, o, *_: tool_ends.append((n, t)),
        ),
    )

    with patch.object(agent.llm, "chat_stream") as mock_stream:
        mock_stream.side_effect = [
            _async_gen([
                ToolCallBegin(index=0, id="call_1", name="nonexistent"),
                ToolCallArgDelta(index=0, arguments='{}'),
            ]),
            _async_gen([
                TextDelta(text="Sorry, I cannot do that."),
            ]),
        ]

        await agent.run_stream("do something", "/tmp")
        assert any(t[1] == "unknown tool" for t in tool_ends)





@pytest.mark.asyncio
async def test_agent_multi_turn_with_session():
    registry = ToolRegistry()
    registry.register(WriteTool())
    collected_text = []

    agent = Agent(
        model="gpt-4o",
        tools=registry,
        api_key="test-key",
        callbacks=AgentCallbacks(on_text_delta=lambda t: collected_text.append(t)),
    )

    session = Session()

    with patch.object(agent.llm, "chat_stream") as mock_stream:
        mock_stream.side_effect = [
            _async_gen([
                TextDelta(text="Created file A."),
            ]),
        ]

        await agent.run_stream("create file A", "/tmp", session=session)
        assert "Created file A." in "".join(collected_text)

    collected_text.clear()

    with patch.object(agent.llm, "chat_stream") as mock_stream:
        mock_stream.side_effect = [
            _async_gen([
                TextDelta(text="Created file B."),
            ]),
        ]

        await agent.run_stream("create file B", "/tmp", session=session)
        assert "Created file B." in "".join(collected_text)
        assert len(session.messages) > 2


