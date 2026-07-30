from types import SimpleNamespace

from nano_claude.core.message import AssistantMessage, DiffSummaryMessage, ToolCall, ToolResult, UserMessage
from nano_claude.core.session import Session
from nano_claude.core.state import AppState


def test_current_view_includes_timeline_and_workspace(tmp_path, monkeypatch):
    app_state = AppState()
    app_state.cwd = str(tmp_path)
    app_state.agent = SimpleNamespace(
        mode="build",
        model="gpt-test",
        provider="test-provider",
        _build_system_prompt=lambda _cwd: "system prompt",
    )

    session = Session(system_prompt="system prompt", title="Test Session")
    session.messages.extend([
        UserMessage(content="hello"),
        AssistantMessage(
            content="hi",
            tool_calls=[ToolCall(id="call-1", name="bash", arguments={"command": "pwd"})],
        ),
        ToolResult(tool_call_id="call-1", tool_name="bash", content="/tmp/project"),
        DiffSummaryMessage(
            checkpoint_filename="cp-1.json",
            summary={"files_changed": 1, "files": [{"path": "a.py", "status": "modified"}]},
        ),
    ])
    session.filepath = str(tmp_path / "session.json")
    session.save(session.filepath)
    session.set_diff_summaries({
        "cp-1.json": {
            "checkpoint_filename": "cp-1.json",
            "summary": {"files_changed": 1, "files": [{"path": "a.py", "status": "modified"}]},
        }
    })
    app_state.session_runtime._session = session

    monkeypatch.setattr(
        app_state.session_runtime,
        "sessions_list",
        lambda: [{"id": "session", "title": "Test Session", "is_current": True}],
    )
    monkeypatch.setattr(
        "nano_claude.core.state.build_workspace_view",
        lambda cwd, diff_summaries, active_diff=None: {
            "plan_docs": [{"filename": "plan.md", "modified": 1, "size": 10}],
            "modified_files": [{"path": "a.py", "status": "M"}],
            "diff_summaries": diff_summaries,
            "active_diff": active_diff,
            "active_diff_files": [{"path": "a.py", "status": "modified"}] if active_diff else [],
        },
    )

    view = app_state.current_view(active_diff="cp-1.json")

    assert view["app"]["mode"] == "build"
    assert view["app"]["active_model"] == "gpt-test"
    assert view["session_meta"]["title"] == "Test Session"
    assert [item["type"] for item in view["conversation"]["timeline"]] == [
        "system",
        "text",
        "text",
        "tool_start",
        "tool_result",
        "diff_summary",
    ]
    assert view["workspace"]["active_diff"] == "cp-1.json"
    assert view["workspace"]["diff_summaries"][0]["checkpoint_filename"] == "cp-1.json"
    assert view["session_catalog"]["sessions"][0]["title"] == "Test Session"


def test_current_view_exposes_pending_interaction(tmp_path):
    app_state = AppState()
    app_state.cwd = str(tmp_path)
    app_state.agent = SimpleNamespace(
        mode="build",
        model="gpt-test",
        provider="test-provider",
        _build_system_prompt=lambda _cwd: "system prompt",
    )

    session = Session(system_prompt="system prompt", title="Test Session")
    session.filepath = str(tmp_path / "session.json")
    session.save(session.filepath)
    app_state.session_runtime._session = session

    loop = __import__("asyncio").new_event_loop()
    try:
        future = loop.create_future()
        app_state.interaction.begin_permission(
            future,
            tool="read",
            target="../secret.txt",
            resolved_path="/tmp/secret.txt",
            cwd=str(tmp_path),
        )
        view = app_state.current_view()
        assert view["app"]["status"] == "awaiting_permission"
        assert view["interaction"]["pending_permission"]["tool"] == "read"
    finally:
        loop.close()


def test_rollback_cutoff_keeps_target_user_message(tmp_path):
    app_state = AppState()
    app_state.cwd = str(tmp_path)
    app_state.agent = SimpleNamespace(
        mode="build",
        model="gpt-test",
        provider="test-provider",
        _build_system_prompt=lambda _cwd: "system prompt",
    )

    session = Session(system_prompt="system prompt", title="Test Session")
    session.messages.extend([
        UserMessage(content="first"),
        AssistantMessage(content="reply 1"),
        UserMessage(content="second"),
        AssistantMessage(content="reply 2"),
    ])
    session.filepath = str(tmp_path / "session.json")
    session.save(session.filepath)
    app_state.session_runtime._session = session

    assert app_state.session_runtime._rollback_cutoff_index(3) == 4
