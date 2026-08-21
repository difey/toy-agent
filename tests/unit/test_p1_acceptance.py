"""P1 验收：CLI 能让 agent 完成「改个文件」任务并落盘事件（含工具循环）。

使用脚本化 mock provider 驱动 file_write 工具；同时验证 CLI 单次执行入口。
"""

import json
from pathlib import Path

from mira.api.client import AppClient
from mira.api.session import SessionManager
from mira.core.providers.mock import MockProvider
from mira.core.providers.router import ProviderRouter
from mira.telemetry.events import EventType


def _write_tool_call(path: str, content: str) -> dict:
    return {
        "id": "call_write",
        "type": "function",
        "function": {
            "name": "file_write",
            "arguments": json.dumps({"path": path, "content": content}),
        },
    }


def _client_with_scripted_provider(reply: str, tool_calls: list[dict]) -> AppClient:
    router = ProviderRouter([MockProvider(id="mock", reply=reply, tool_calls=tool_calls)])
    return AppClient(SessionManager(router=router))


def _run_to_end(client: AppClient, session_id: str) -> list:
    events = []
    for ev in client.events(session_id):
        events.append(ev)
        if ev.type == EventType.SESSION_STATUS and ev.payload.get("status") in ("idle", "failed"):
            break
    return events


def test_p1_acceptance_write_file(tmp_path: Path):
    client = _client_with_scripted_provider(
        "已创建 notes.txt",
        [_write_tool_call("notes.txt", "# 笔记\nhello")],
    )
    sess = client.create_session(tmp_path, agent_type="main")
    client.send_message(sess.id, "请创建 notes.txt", model=sess.model)
    events = _run_to_end(client, sess.id)

    # 文件真实被创建（工具循环生效）
    assert (tmp_path / "notes.txt").read_text() == "# 笔记\nhello"
    # 事件含 工具调用/结果 与 最终回复
    types = [e.type for e in events]
    assert EventType.TOOL_CALL in types
    assert EventType.TOOL_RESULT in types
    assert EventType.AGENT_MESSAGE in types
    assert client.get_session(sess.id).status.value == "idle"


def test_p1_acceptance_cli_one_shot(tmp_path: Path, capsys):
    client = _client_with_scripted_provider(
        "搞定，文件已写好",
        [_write_tool_call("result.txt", "done")],
    )
    from mira.cli.app import main

    ret = main(
        ["-p", "请创建 result.txt", "-w", str(tmp_path), "-q"],
        client=client,
    )
    out = capsys.readouterr().out
    assert ret == 0
    assert "搞定" in out  # 静默模式输出最终回复
    assert (tmp_path / "result.txt").read_text() == "done"


def test_p1_acceptance_repl_no_tools_streams(tmp_path: Path, capsys, monkeypatch):
    """无工具 mock：REPL 收到流式 token 与最终回复。"""
    import builtins

    inputs = iter(["你好", "/exit"])
    monkeypatch.setattr(builtins, "input", lambda *a, **k: next(inputs))
    from mira.cli.app import main

    ret = main(["chat", "-w", str(tmp_path)], client=_client_with_scripted_provider("收到你的消息", []))
    assert ret == 0
    out = capsys.readouterr().out
    assert "Mira Code" in out
