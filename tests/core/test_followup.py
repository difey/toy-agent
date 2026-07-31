"""Tests for follow-up interjections submitted while an AI response is running."""

import pytest
from types import SimpleNamespace
from unittest.mock import patch

from nano_claude.core.agent import Agent
from nano_claude.core.message import TextDelta, ToolCall, ToolCallBegin, ToolCallArgDelta
from nano_claude.core.session import Session
from nano_claude.core.session_runtime import SessionRuntime
from nano_claude.core.state import AppState
from nano_claude.core.tool_registry import ToolRegistry
from nano_claude.tools import WriteTool


# ── SessionRuntime queue ──────────────────────────────────────────────

def test_submit_followup_stores_interjection():
    runtime = SessionRuntime(cwd_getter=lambda: "/tmp", agent_getter=lambda: None)
    runtime.submit_followup("chat_1", "别用 bash，改用 python", "chat_1")
    assert runtime.interjections_pending() is True
    items = runtime.pop_pending_interjections()
    assert len(items) == 1
    assert items[0]["response_id"] == "chat_1"
    assert items[0]["message"] == "别用 bash，改用 python"
    assert runtime.interjections_pending() is False


def test_submit_followup_rejects_mismatched_response_id():
    runtime = SessionRuntime(cwd_getter=lambda: "/tmp", agent_getter=lambda: None)
    with pytest.raises(RuntimeError):
        runtime.submit_followup("chat_2", "说明", "chat_1")


def test_submit_followup_rejects_when_nothing_running():
    runtime = SessionRuntime(cwd_getter=lambda: "/tmp", agent_getter=lambda: None)
    with pytest.raises(RuntimeError):
        runtime.submit_followup("chat_1", "说明", None)


# ── AppState submit_followup / stop cleanup ───────────────────────────

def test_state_submit_followup_requires_running():
    app = AppState()
    app.cwd = "/tmp"
    app.session_runtime._session = Session(system_prompt="sys")
    with pytest.raises(RuntimeError):
        app.submit_followup("chat_1", "说明")


def test_state_submit_followup_matches_running_response_id():
    app = AppState()
    app.cwd = "/tmp"
    app.session_runtime._session = Session(system_prompt="sys")
    app._running = True
    app._running_response_id = "chat_1"
    app.submit_followup("chat_1", "说明")
    assert app.session_runtime.interjections_pending() is True


def test_stop_running_clears_pending_interjections():
    app = AppState()
    app.cwd = "/tmp"
    app.session_runtime._session = Session(system_prompt="sys")
    app.session_runtime.pending_interjections.append(
        {"response_id": "chat_1", "message": "说明", "timestamp": 0.0}
    )
    app._running = True
    app._running_task = SimpleNamespace(cancel=lambda: None)
    app.stop_running()
    assert app.session_runtime.interjections_pending() is False


# ── Agent.run_stream consumes interjections ───────────────────────────

def _async_gen(items):
    async def gen():
        for item in items:
            yield item
    return gen()


@pytest.mark.asyncio
async def test_agent_stream_consumes_interjection_between_turns():
    """额外说明应作为新的 user message 插入，并在下一次 LLM 调用前可见。

    run_stream 只有在响应包含 tool call 时才会继续循环，因此用一个真实的
    write tool call 驱动第一轮，随后第二轮响应文本。
    """
    registry = ToolRegistry()
    registry.register(WriteTool())
    collected_text = []
    interjections = [{"response_id": "chat_1", "message": "改成用中文回复"}]

    agent = Agent(
        model="gpt-4o",
        tools=registry,
        api_key="test-key",
        on_text_delta=lambda t: collected_text.append(t),
        interjection_source=lambda: [interjections.pop(0)] if interjections else [],
    )

    session = Session()

    with patch.object(agent.llm, "chat_stream") as mock_stream:
        # 第一轮：文本 + write tool call，触发循环继续
        mock_stream.side_effect = [
            _async_gen([
                TextDelta(text="第一段回复"),
                ToolCallBegin(index=0, id="call_1", name="write"),
                ToolCallArgDelta(index=0, arguments='{"filePath": "/tmp/followup.txt", "content": "x"}'),
            ]),
            # 第二轮：被纠正后的回复，无 tool call，循环结束
            _async_gen([
                TextDelta(text="被纠正后的回复"),
            ]),
        ]

        await agent.run_stream("帮我改个文件", "/tmp", session=session)
        assert "被纠正后的回复" in "".join(collected_text)

    # 额外说明已作为 user message 插入 session
    user_texts = [m.content for m in session.messages if m.__class__.__name__ == "UserMessage"]
    assert "改成用中文回复" in user_texts
    # 插入位置在原 user 消息之后
    assert user_texts.index("改成用中文回复") > user_texts.index("帮我改个文件")


@pytest.mark.asyncio
async def test_agent_stream_consumes_interjection_arriving_during_final_response():
    """额外说明在最后一轮 LLM 调用（无 tool call）期间到达时，
    agent 应再跑一轮来回应它，而不是直接结束。
    """
    registry = ToolRegistry()
    registry.register(WriteTool())
    collected_text = []
    interjections = [{"response_id": "chat_1", "message": "等等，先别提交"}]
    calls = {"n": 0}

    def interjection_source():
        # 前两次消费（循环顶部）返回空，模拟说明在最终回复进行中才到达；
        # 第三次消费（最终回复结束后）才返回说明，触发再跑一轮。
        calls["n"] += 1
        if calls["n"] >= 3:
            return [interjections.pop(0)] if interjections else []
        return []

    agent = Agent(
        model="gpt-4o",
        tools=registry,
        api_key="test-key",
        on_text_delta=lambda t: collected_text.append(t),
        interjection_source=interjection_source,
    )

    session = Session()

    with patch.object(agent.llm, "chat_stream") as mock_stream:
        mock_stream.side_effect = [
            # 第一轮：文本 + write tool call，触发循环继续
            _async_gen([
                TextDelta(text="第一段"),
                ToolCallBegin(index=0, id="call_1", name="write"),
                ToolCallArgDelta(index=0, arguments='{"filePath": "/tmp/followup3.txt", "content": "x"}'),
            ]),
            # 第二轮：最终回复（无 tool call）——额外说明此刻才到达
            _async_gen([TextDelta(text="最终回复")]),
            # 第三轮：回应额外说明
            _async_gen([TextDelta(text="收到，暂停提交")]),
        ]
        await agent.run_stream("帮我改文件", "/tmp", session=session)

    assert "收到，暂停提交" in "".join(collected_text)
    user_texts = [m.content for m in session.messages if m.__class__.__name__ == "UserMessage"]
    assert "等等，先别提交" in user_texts
    # 额外说明插入在第一条 user 消息之后
    assert user_texts.index("等等，先别提交") > user_texts.index("帮我改文件")


@pytest.mark.asyncio
async def test_agent_stream_no_interjection_source_is_unchanged():
    """未注入 interjection_source 时行为不变（正常循环行为）。"""
    registry = ToolRegistry()
    registry.register(WriteTool())
    collected_text = []
    agent = Agent(
        model="gpt-4o",
        tools=registry,
        api_key="test-key",
        on_text_delta=lambda t: collected_text.append(t),
    )
    session = Session()

    with patch.object(agent.llm, "chat_stream") as mock_stream:
        mock_stream.side_effect = [
            _async_gen([
                TextDelta(text="第一段"),
                ToolCallBegin(index=0, id="call_1", name="write"),
                ToolCallArgDelta(index=0, arguments='{"filePath": "/tmp/followup2.txt", "content": "x"}'),
            ]),
            _async_gen([TextDelta(text="第二段")]),
        ]
        await agent.run_stream("hi", "/tmp", session=session)
        assert "".join(collected_text) == "第一段第二段"
        # 无额外说明插入
        user_texts = [m.content for m in session.messages if m.__class__.__name__ == "UserMessage"]
        assert user_texts == ["hi"]
