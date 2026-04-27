from unittest.mock import patch

import pytest

from nano_claude.agent import Agent
from nano_claude.config import ProviderConfig, detect_provider, resolve_config, PROVIDERS
from nano_claude.message import AssistantMessage, TextDelta, ToolCall, ToolCallBegin, ToolCallArgDelta
from nano_claude.session import Session, estimate_tokens, message_tokens
from nano_claude.tool import ToolContext, ToolRegistry
from nano_claude.tools import (
    ApplyPatchTool,
    BashTool,
    CodeSearchTool,
    EditTool,
    GlobTool,
    GrepTool,
    QuestionTool,
    ReadTool,
    TodoWriteTool,
    WebFetchTool,
    WebSearchTool,
    WriteTool,
)


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
        mock_chat.assert_awaited_once()


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
        on_text_delta=lambda t: collected_text.append(t),
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
        on_text_delta=lambda t: collected_text.append(t),
        on_tool_start=lambda tc: tool_starts.append(tc.name),
        on_tool_end=lambda n, t, o: tool_ends.append((n, t)),
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
        on_tool_end=lambda n, t, o: tool_ends.append((n, t)),
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
async def test_read_tool(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("line1\nline2\nline3\nline4\nline5\n")
    tool = ReadTool()
    ctx = ToolContext(cwd=str(tmp_path))

    r = await tool.execute({"filePath": str(f)}, ctx)
    assert "line1" in r.output
    assert "line5" in r.output

    r = await tool.execute({"filePath": str(f), "offset": 2, "limit": 2}, ctx)
    assert "line1" not in r.output
    assert "line2" in r.output
    assert "line3" in r.output
    assert "line4" not in r.output

    r = await tool.execute({"filePath": str(tmp_path / "nonexistent.txt")}, ctx)
    assert "error" in r.title


@pytest.mark.asyncio
async def test_edit_tool(tmp_path):
    f = tmp_path / "edit.txt"
    f.write_text("hello world\nfoo bar\nhello world\n")
    tool = EditTool()
    ctx = ToolContext(cwd=str(tmp_path))

    r = await tool.execute({"filePath": str(f), "oldString": "hello world", "newString": "hi", "replaceAll": True}, ctx)
    assert "Successfully" in r.output
    assert f.read_text() == "hi\nfoo bar\nhi\n"

    r = await tool.execute({"filePath": str(f), "oldString": "nonexistent", "newString": "x"}, ctx)
    assert "not found" in r.output.lower()

    f.write_text("dup\nunique\ndup\n")
    r = await tool.execute({"filePath": str(f), "oldString": "dup", "newString": "x"}, ctx)
    assert "Found 2 matches" in r.output


@pytest.mark.asyncio
async def test_glob_tool(tmp_path):
    (tmp_path / "a.py").write_text("x")
    (tmp_path / "b.txt").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.py").write_text("x")
    tool = GlobTool()
    ctx = ToolContext(cwd=str(tmp_path))

    r = await tool.execute({"pattern": "*.py", "path": str(tmp_path)}, ctx)
    assert "a.py" in r.output
    assert "b.txt" not in r.output

    r = await tool.execute({"pattern": "**/*.py", "path": str(tmp_path)}, ctx)
    assert "c.py" in r.output

    r = await tool.execute({"pattern": "*.rs", "path": str(tmp_path)}, ctx)
    assert "no matches" in r.output.lower()


@pytest.mark.asyncio
async def test_grep_tool(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("def foo():\n    return bar()\n\ndef baz():\n    pass\n")
    tool = GrepTool()
    ctx = ToolContext(cwd=str(tmp_path))

    r = await tool.execute({"pattern": "def", "path": str(tmp_path)}, ctx)
    assert "def foo" in r.output
    assert "def baz" in r.output

    r = await tool.execute({"pattern": "bar", "path": str(tmp_path)}, ctx)
    assert "bar" in r.output
    assert "def foo" not in r.output

    r = await tool.execute({"pattern": "xyz_none", "path": str(tmp_path)}, ctx)
    assert "no matches" in r.output.lower()


def test_registry_all_tools():
    registry = ToolRegistry()
    registry.register(BashTool())
    registry.register(ReadTool())
    registry.register(WriteTool())
    registry.register(EditTool())
    registry.register(GlobTool())
    registry.register(GrepTool())
    registry.register(WebFetchTool())
    registry.register(WebSearchTool())
    registry.register(CodeSearchTool())
    registry.register(TodoWriteTool())
    registry.register(QuestionTool())
    registry.register(ApplyPatchTool())

    tools = registry.to_openai_tools()
    assert len(tools) == 12
    names = {t["function"]["name"] for t in tools}
    assert names == {
        "bash", "read", "write", "edit", "glob", "grep",
        "webfetch", "websearch", "codesearch",
        "todowrite", "question", "apply_patch",
    }


def test_estimate_tokens():
    assert estimate_tokens("hello") == 1
    assert estimate_tokens("a" * 100) == 25


def test_session_create():
    s = Session(system_prompt="You are a helpful assistant.")
    assert len(s.messages) == 1
    assert s.messages[0].content == "You are a helpful assistant."


@pytest.mark.asyncio
async def test_session_add_messages():
    s = Session()
    await s.add_user_message("hello")
    assert len(s.messages) == 1
    assert s.messages[0].content == "hello"


@pytest.mark.asyncio
async def test_session_total_tokens():
    s = Session()
    await s.add_user_message("hello world!")
    assert s.total_tokens() > 0


@pytest.mark.asyncio
async def test_session_compact():
    s = Session(max_tokens=100)
    await s.add_user_message("first message that takes some tokens " * 5)
    await s.add_user_message("second message also taking tokens " * 5)
    assert len(s.messages) == 2

    s.max_tokens = 1
    await s._compact()
    assert len(s.messages) == 1


@pytest.mark.asyncio
async def test_session_save_load(tmp_path):
    s = Session(system_prompt="test")
    await s.add_user_message("hello")
    p = str(tmp_path / "session.json")
    s.save(p)

    s2 = Session.load(p)
    assert len(s2.messages) == 2
    assert s2.messages[0].content == "test"
    assert s2.messages[1].content == "hello"


@pytest.mark.asyncio
async def test_agent_multi_turn_with_session():
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


def test_detect_provider_openai():
    assert detect_provider("gpt-4o") == "openai"
    assert detect_provider("gpt-4.1-mini") == "openai"
    assert detect_provider("o1-preview") == "openai"
    assert detect_provider("o4-mini") == "openai"


def test_detect_provider_deepseek():
    assert detect_provider("deepseek-chat") == "deepseek"
    assert detect_provider("deepseek-reasoner") == "deepseek"
    assert detect_provider("deepseek-chat-v3") == "deepseek"


def test_detect_provider_anthropic():
    assert detect_provider("claude-sonnet-4-20250514") == "anthropic"
    assert detect_provider("claude-3-5-sonnet") == "anthropic"


def test_detect_provider_unknown():
    assert detect_provider("some-unknown-model") == "openai"


def test_resolve_config_deepseek(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.delenv("NANO_CLAUDE_MODEL", raising=False)
    config = resolve_config("deepseek-chat")
    assert config.name == "deepseek"
    assert config.api_key == "sk-test"
    assert config.base_url == "https://api.deepseek.com/v1"
    assert config.default_model == "deepseek-chat"


def test_resolve_config_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.delenv("NANO_CLAUDE_MODEL", raising=False)
    config = resolve_config("gpt-4o")
    assert config.name == "openai"
    assert config.api_key == "sk-openai"
    assert config.default_model == "gpt-4o"


def test_resolve_config_ollama(monkeypatch):
    monkeypatch.setenv("NANO_CLAUDE_PROVIDER", "ollama")
    config = resolve_config("llama3")
    assert config.name == "ollama"


def test_resolve_config_generic_key(monkeypatch):
    monkeypatch.setenv("NANO_CLAUDE_API_KEY", "sk-generic")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    config = resolve_config("deepseek-chat")
    assert config.api_key == "sk-generic"


def test_providers_registered():
    assert "openai" in PROVIDERS
    assert "deepseek" in PROVIDERS
    assert "anthropic" in PROVIDERS
    assert "ollama" in PROVIDERS
    assert PROVIDERS["deepseek"].base_url == "https://api.deepseek.com/v1"


def test_user_config_save_load(tmp_path, monkeypatch):
    import nano_claude.setup as setup
    config_dir = tmp_path / ".my_code"
    config_file = config_dir / "config.toml"
    monkeypatch.setattr(setup, "CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(setup, "CONFIG_FILE", str(config_file))

    assert not setup.has_user_config()

    setup.save_user_config("deepseek-chat", "sk-test-123")
    assert setup.has_user_config()

    cfg = setup.load_user_config()
    assert cfg["model"] == "deepseek-chat"
    assert cfg["api_key"] == "sk-test-123"


def test_resolve_config_uses_user_config(tmp_path, monkeypatch):
    import nano_claude.setup as setup
    config_dir = tmp_path / "my_code"
    config_file = config_dir / "config.toml"
    monkeypatch.setattr(setup, "CONFIG_DIR", str(config_dir))
    monkeypatch.setattr(setup, "CONFIG_FILE", str(config_file))

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("NANO_CLAUDE_API_KEY", raising=False)
    monkeypatch.delenv("NANO_CLAUDE_MODEL", raising=False)

    setup.save_user_config("deepseek-chat", "sk-from-file")

    config = resolve_config()
    assert config.default_model == "deepseek-chat"
    assert config.api_key == "sk-from-file"
    assert config.name == "deepseek"


@pytest.mark.asyncio
async def test_webfetch_rejects_invalid_url():
    tool = WebFetchTool()
    ctx = ToolContext(cwd="/tmp")
    r = await tool.execute({"url": "not-a-url"}, ctx)
    assert "error" in r.title


@pytest.mark.asyncio
async def test_webfetch_upgrades_http():
    tool = WebFetchTool()
    ctx = ToolContext(cwd="/tmp")
    r = await tool.execute({"url": "http://example.com"}, ctx)
    assert "webfetch" in r.title


@pytest.mark.asyncio
async def test_websearch_missing_query():
    from nano_claude.tools.exa_client import call_exa_tool
    from unittest.mock import AsyncMock, patch

    with patch("nano_claude.tools.websearch.call_exa_tool") as mock_call:
        mock_call.return_value = None
        tool = WebSearchTool()
        ctx = ToolContext(cwd="/tmp")
        r = await tool.execute({"query": "nothing matches this"}, ctx)
        assert r.output == "No search results found."


@pytest.mark.asyncio
async def test_codesearch_missing_query():
    from unittest.mock import patch

    with patch("nano_claude.tools.codesearch.call_exa_tool") as mock_call:
        mock_call.return_value = None
        tool = CodeSearchTool()
        ctx = ToolContext(cwd="/tmp")
        r = await tool.execute({"query": "nothing matches this"}, ctx)
        assert r.output == "No code documentation found."


def test_todowrite_tool_basic():
    tool = TodoWriteTool()
    assert tool.name == "todowrite"
    assert "todo" in tool.description.lower()


@pytest.mark.asyncio
async def test_todowrite_execute(tmp_path):
    import nano_claude.tools.todowrite as td
    td.TODO_STORE_FILE = str(tmp_path / "todos.json")

    tool = TodoWriteTool()
    ctx = ToolContext(cwd="/tmp")
    todos = [
        {"content": "Task 1", "status": "completed", "priority": "high"},
        {"content": "Task 2", "status": "in_progress", "priority": "medium"},
        {"content": "Task 3", "status": "pending", "priority": "low"},
    ]
    r = await tool.execute({"todos": todos}, ctx)
    assert "1 completed" in r.title
    assert "2 active" in r.title
    assert "Task 1" in r.output


def test_question_tool_basic():
    tool = QuestionTool()
    assert tool.name == "question"


@pytest.mark.asyncio
async def test_question_no_callback():
    tool = QuestionTool()
    ctx = ToolContext(cwd="/tmp")
    r = await tool.execute({
        "questions": [{
            "question": "Test?",
            "header": "Test",
            "options": [{"label": "A", "description": "Option A"}],
        }]
    }, ctx)
    assert "error" in r.title


@pytest.mark.asyncio
async def test_question_with_callback():
    tool = QuestionTool()
    async def fake_ask(header, question, options, multiple):
        return ["A"]
    ctx = ToolContext(cwd="/tmp", ask_user_callback=fake_ask)
    r = await tool.execute({
        "questions": [{
            "question": "Test?",
            "header": "Test",
            "options": [{"label": "A", "description": "Option A"}],
        }]
    }, ctx)
    assert "answered" in r.title
    assert "A" in r.output


def test_apply_patch_tool_basic():
    tool = ApplyPatchTool()
    assert tool.name == "apply_patch"


@pytest.mark.asyncio
async def test_apply_patch_add(tmp_path):
    tool = ApplyPatchTool()
    ctx = ToolContext(cwd=str(tmp_path))
    r = await tool.execute({
        "patchText": "*** Add File: hello.txt\n+Hello world\n+Second line\n"
    }, ctx)
    assert "1 files" in r.title
    assert (tmp_path / "hello.txt").exists()
    assert (tmp_path / "hello.txt").read_text() == "Hello world\nSecond line"


@pytest.mark.asyncio
async def test_apply_patch_delete(tmp_path):
    f = tmp_path / "delete_me.txt"
    f.write_text("content")
    tool = ApplyPatchTool()
    ctx = ToolContext(cwd=str(tmp_path))
    r = await tool.execute({
        "patchText": "*** Delete File: delete_me.txt\n"
    }, ctx)
    assert "1 files" in r.title
    assert not f.exists()


@pytest.mark.asyncio
async def test_apply_patch_empty():
    tool = ApplyPatchTool()
    ctx = ToolContext(cwd="/tmp")
    r = await tool.execute({"patchText": ""}, ctx)
    assert "error" in r.title


@pytest.mark.asyncio
async def test_apply_patch_update(tmp_path):
    f = tmp_path / "update.txt"
    f.write_text("old line\nkeep this\n")
    tool = ApplyPatchTool()
    ctx = ToolContext(cwd=str(tmp_path))
    r = await tool.execute({
        "patchText": (
            "*** Update File: update.txt\n"
            "@@ -1,1 +1,1 @@\n"
            "-old line\n"
            "+new line\n"
        )
    }, ctx)
    assert "1 files" in r.title
    assert (tmp_path / "update.txt").read_text() == "new line\nkeep this\n"
