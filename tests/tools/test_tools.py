import pytest

from nano_claude.core.tool_contracts import ToolContext
from nano_claude.core.tool_registry import ToolRegistry
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
    assert "modified after it was last read" in r.output

    ctx.file_read_registry.record_read(str(f), f.stat().st_mtime)
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
    ctx.file_read_registry.record_read(str(tmp_path / "hello.txt"), None)
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
    ctx.file_read_registry.record_read(str(f), f.stat().st_mtime)
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


@pytest.mark.asyncio
async def test_bash_search_guard_detection():
    """Test that file-search commands are detected."""
    from nano_claude.tools.bash import (
        SEARCH_COMMAND_PATTERNS,
        SEARCH_COMMAND_TIMEOUT,
        HEAVY_DIRS_TO_EXCLUDE,
    )

    tool = BashTool()

    # Commands that SHOULD be detected as search
    search_cmds = [
        "find . -name '*.py'",
        "find . -type f",
        "grep -r 'pattern' .",
        "grep -rn 'pattern' .",
        "grep -rli 'pattern' .",
        "rg 'pattern'",
        "ag 'pattern'",
        "ack 'pattern'",
        "fd 'pattern'",
        "locate something",
    ]
    for cmd in search_cmds:
        reason, timeout = tool._detect_search_command(cmd)
        assert reason, f"Command should be detected as search: {cmd}"
        assert timeout == SEARCH_COMMAND_TIMEOUT, f"Timeout should be {SEARCH_COMMAND_TIMEOUT}"

    # Commands that should NOT be detected
    non_search_cmds = [
        "echo hello",
        "ls -la",
        "python script.py",
        "npm install",
        "grep 'pattern' file.txt",  # non-recursive grep on a single file
        "cat file.txt",
        "cd /tmp && pwd",
        "pip install requests",
        "touch newfile.txt",
    ]
    for cmd in non_search_cmds:
        reason, timeout = tool._detect_search_command(cmd)
        assert not reason, f"Command should NOT be detected as search: {cmd} ({reason})"


@pytest.mark.asyncio
async def test_bash_search_guard_exclusions(tmp_path):
    """Test that heavy dir exclusions are auto-added to search commands."""
    tool = BashTool()

    # Create some heavy directories
    (tmp_path / ".git").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "__pycache__").mkdir()

    # Test find command auto-exclusion
    modified = tool._auto_exclude_heavy_dirs("find . -name '*.py'", str(tmp_path))
    assert '.git' in modified
    assert 'node_modules' in modified
    assert '__pycache__' in modified
    assert '-not -path' in modified

    # Test grep auto-exclusion
    modified = tool._auto_exclude_heavy_dirs("grep -r 'pattern' .", str(tmp_path))
    assert '--exclude-dir=".git"' in modified
    assert '--exclude-dir="node_modules"' in modified

    # Test rg auto-exclusion
    modified = tool._auto_exclude_heavy_dirs("rg 'pattern' .", str(tmp_path))
    assert '--exclude-dir=".git"' in modified

    # Test fd auto-exclusion
    modified = tool._auto_exclude_heavy_dirs("fd 'pattern'", str(tmp_path))
    assert '--exclude=".git"' in modified


@pytest.mark.asyncio
async def test_bash_search_guard_no_exclusions_when_no_heavy_dirs(tmp_path):
    """Test that no exclusions are added when heavy dirs don't exist."""
    tool = BashTool()

    modified = tool._auto_exclude_heavy_dirs("find . -name '*.py'", str(tmp_path))
    assert modified == "find . -name '*.py'", "No modification expected when heavy dirs don't exist"

    modified = tool._auto_exclude_heavy_dirs("grep -r 'pattern' .", str(tmp_path))
    assert modified == "grep -r 'pattern' .", "No modification expected when heavy dirs don't exist"


@pytest.mark.asyncio
async def test_bash_search_guard_execute_adds_warning(tmp_path):
    """Test that executing a search command via bash adds a warning."""
    tool = BashTool()
    ctx = ToolContext(cwd=str(tmp_path))

    # Run a simple find on an empty temp dir (should complete quickly)
    result = await tool.execute({"command": "find . -maxdepth 1 -type f", "description": "test find"}, ctx)

    # Should include search guard warning
    assert "[Search guard]" in result.output
    assert "Detected:" in result.output
    assert "glob" in result.output or "grep" in result.output


@pytest.mark.asyncio
async def test_bash_non_search_no_warning(tmp_path):
    """Test that non-search commands don't get a warning."""
    tool = BashTool()
    ctx = ToolContext(cwd=str(tmp_path))

    result = await tool.execute({"command": "echo 'hello world'", "description": "test echo"}, ctx)

    assert "[Search guard]" not in result.output
    assert result.title == "bash [test echo]"
