"""API tests for the follow-up interjection endpoint (/api/chat with response_id)."""

import pytest
from fastapi.testclient import TestClient
from types import SimpleNamespace

from nano_claude.core.state import AppState, state
from nano_claude.interfaces.web.app import app


@pytest.fixture
def client(monkeypatch):
    """Use an isolated AppState and ensure the app routes use it."""
    app_state = AppState()
    app_state.cwd = "/tmp"
    # Session must exist for followup validation (submit_followup accesses session_runtime)
    from nano_claude.core.session import Session

    app_state.session_runtime._session = Session(system_prompt="sys")
    # A stub agent bypasses the "please configure" guard and supports current_info()
    app_state.agent = SimpleNamespace(mode="build", model="test-model", provider="test")
    # Override run_chat so the fallback path returns a response_id without spawning a task
    async def fake_run_chat():
        app_state._running = False
        return "chat_fallback"

    app_state.run_chat = fake_run_chat  # type: ignore

    monkeypatch.setattr("nano_claude.interfaces.web.routers.chat.state", app_state)
    return TestClient(app)


def test_followup_accepted_when_running(client):
    app_state = client.app.state  # not used
    from nano_claude.interfaces.web.routers import chat

    app_state = chat.state
    app_state._running = True
    app_state._running_response_id = "chat_1"

    resp = client.post("/api/chat", json={"message": "别用 bash", "response_id": "chat_1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is True
    assert body["response_id"] == "chat_1"
    assert app_state.session_runtime.interjections_pending() is True


def test_followup_falls_back_when_not_running(client):
    """当前没有正在运行的回复时，带 response_id 的消息应回落到正常发送路径。"""
    from nano_claude.interfaces.web.routers import chat

    app_state = chat.state
    app_state._running = False
    app_state._running_response_id = None

    resp = client.post("/api/chat", json={"message": "这是一条新消息", "response_id": "chat_1"})
    assert resp.status_code == 200
    body = resp.json()
    # 回落路径返回新的 response_id + 完整 current state（与正常发送一致）
    assert body["response_id"] == "chat_fallback"
    assert "current" in body
    # 消息已作为普通 user message 插入 session
    user_texts = [
        m.content for m in app_state.session.messages if m.__class__.__name__ == "UserMessage"
    ]
    assert "这是一条新消息" in user_texts
    # 队列中没有残留的额外说明（走的是正常发送而非入队）
    assert app_state.session_runtime.interjections_pending() is False


def test_followup_rejected_on_mismatched_response_id(client):
    from nano_claude.interfaces.web.routers import chat

    app_state = chat.state
    app_state._running = True
    app_state._running_response_id = "chat_2"

    resp = client.post("/api/chat", json={"message": "说明", "response_id": "chat_1"})
    assert resp.status_code == 409


def test_followup_requires_message(client):
    from nano_claude.interfaces.web.routers import chat

    app_state = chat.state
    app_state._running = True
    app_state._running_response_id = "chat_1"

    resp = client.post("/api/chat", json={"message": "   ", "response_id": "chat_1"})
    assert resp.status_code == 400
