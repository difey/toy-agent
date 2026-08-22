"""P2 集成测试：Web 后端（REST + WebSocket 透传 + 审批 + 配额）。

conftest 已把 MIRA_HOME 隔离到临时目录。
"""

import json
import time

from fastapi.testclient import TestClient

from mira import paths
from mira.api.client import AppClient
from mira.api.session import SessionManager
from mira.core.config.store import global_config_dir, seed_global_config
from mira.core.providers.mock import MockProvider
from mira.core.providers.router import ProviderRouter
from mira.web.server import create_app


def _client_with_scripted(reply: str = "搞定", tool_calls: list | None = None) -> AppClient:
    router = ProviderRouter(
        [MockProvider(id="mock", reply=reply, tool_calls=tool_calls)]
    )
    return AppClient(SessionManager(router=router))


def _shell_tool_call(cmd: str = "echo ok") -> dict:
    return {
        "id": "c_shell",
        "type": "function",
        "function": {"name": "shell", "arguments": json.dumps({"cmd": cmd})},
    }


def test_health_meta_and_sessions(tmp_path):
    app = create_app(_client_with_scripted())
    c = TestClient(app)
    assert c.get("/api/health").json()["ok"]
    meta = c.get("/api/meta").json()
    assert any(a["id"] == "main" for a in meta["agents"])
    assert any(p["id"] == "mock" for p in meta["providers"])

    r = c.post("/api/sessions", json={"workspace": str(tmp_path)})
    assert r.status_code == 201
    sid = r.json()["id"]
    assert any(s["id"] == sid for s in c.get("/api/sessions").json())
    assert c.get(f"/api/sessions/{sid}").json()["id"] == sid


def test_api_tools_lists_registered_builtins(tmp_path):
    """配置中心工具候选来自 /api/tools（内建工具注册表），新增工具自动出现，不写死。"""
    app = create_app(_client_with_scripted())
    c = TestClient(app)
    r = c.get("/api/tools")
    assert r.status_code == 200
    tools = r.json()["tools"]
    # 核心内建工具
    for t in ["shell", "file_read", "file_write", "file_edit", "search_grep",
              "glob", "todowrite", "apply_patch", "project_memory", "web_fetch",
              "web_search", "attach_image"]:
        assert t in tools
    # dispatch_task 由 session runtime 动态注册，但须出现在配置中心候选
    assert "dispatch_task" in tools
    # 与注册表一致（无多余/遗漏），外加 dispatch_task
    from mira.core.tools.registry import ToolRegistry
    assert set(tools) == set(ToolRegistry.with_builtins().names()) | {"dispatch_task"}



def test_fs_list(tmp_path):
    """引用文件选择器：工作区内目录浏览，目录在前、文件在后，防目录穿越。"""
    app = create_app(_client_with_scripted())
    c = TestClient(app)
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("y", encoding="utf-8")

    r = c.get("/api/fs/list", params={"path": str(tmp_path)})
    assert r.status_code == 200
    data = r.json()
    assert data["path"] == str(tmp_path.resolve())
    assert data["parent"] == str(tmp_path.resolve().parent)
    # 目录全部排在文件之前（环境可能产生 .mira-code 等目录，只校验顺序与关键条目）
    seen_file = False
    for e in data["entries"]:
        if e["type"] == "file":
            seen_file = True
        else:
            assert not seen_file, "目录必须排在文件之前"
    sub = next(e for e in data["entries"] if e["name"] == "sub")
    assert sub["type"] == "dir" and sub["path"] == str((tmp_path / "sub").resolve())
    assert any(e["name"] == "a.py" and e["type"] == "file" for e in data["entries"])

    # 子目录 + 上级（绝对路径）
    r2 = c.get("/api/fs/list", params={"path": str(tmp_path / "sub")})
    assert r2.status_code == 200
    d2 = r2.json()
    assert [e["name"] for e in d2["entries"]] == ["b.txt"]
    assert d2["path"] == str((tmp_path / "sub").resolve())
    assert d2["parent"] == str(tmp_path.resolve())

    # 空 path = 根目录（不限制工作区）
    assert c.get("/api/fs/list").json()["path"] == "/"

    # 非目录 / 不存在的路径 → 400
    assert c.get("/api/fs/list", params={"path": str(tmp_path / "a.py")}).status_code == 400
    assert c.get("/api/fs/list", params={"path": str(tmp_path / "nope")}).status_code == 400


def test_send_message_with_attachments(tmp_path):
    """发送消息携带 attachments：正常触发一轮 agent 回复（mock 立即完成）。"""
    app = create_app(_client_with_scripted("分析完毕"))
    c = TestClient(app)
    sid = c.post("/api/sessions", json={"workspace": str(tmp_path)}).json()["id"]
    (tmp_path / "a.py").write_text("x = 1", encoding="utf-8")

    r = c.post(
        f"/api/sessions/{sid}/messages",
        json={"content": "请分析", "model": "mock/mock-model", "attachments": [str(tmp_path / "a.py")]},
    )
    assert r.status_code == 200 and r.json()["accepted"]
    time.sleep(1.2)  # 等 mock 轮次完成
    events = c.get(f"/api/sessions/{sid}/events").json()
    assert any(e["type"] == "agent.message" for e in events)


def test_send_message_with_image_attachment(tmp_path):
    """发送消息携带图片附件：按扩展名区分图片，正常触发一轮回复。"""
    app = create_app(_client_with_scripted("看到了图片"))
    c = TestClient(app)
    sid = c.post("/api/sessions", json={"workspace": str(tmp_path)}).json()["id"]
    (tmp_path / "shot.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    r = c.post(
        f"/api/sessions/{sid}/messages",
        json={"content": "描述这张图", "model": "mock/mock-model", "attachments": [str(tmp_path / "shot.png")]},
    )
    assert r.status_code == 200 and r.json()["accepted"]
    time.sleep(1.2)
    events = c.get(f"/api/sessions/{sid}/events").json()
    assert any(e["type"] == "agent.message" for e in events)


def test_send_message_streams_over_ws(tmp_path):
    app = create_app(_client_with_scripted("你好，世界"))
    c = TestClient(app)
    sid = c.post("/api/sessions", json={"workspace": str(tmp_path)}).json()["id"]

    with c.websocket_connect(f"/api/ws/sessions/{sid}") as ws:
        ws.send_json({"last_seq": 0})
        c.post(f"/api/sessions/{sid}/messages", json={"content": "你好", "model": "mock/mock-model"})
        types = []
        for _ in range(40):
            ev = ws.receive_json()
            types.append(ev["type"])
            if ev["type"] == "session.status" and ev["payload"]["status"] == "idle":
                break
        assert "user.message" in types
        assert "llm.request" in types
        assert "llm.stream_chunk" in types
        assert "agent.loop.end" in types
    assert c.get(f"/api/sessions/{sid}").json()["status"] == "idle"


def test_approval_block_and_resolve(tmp_path):
    app = create_app(_client_with_scripted("完成", [_shell_tool_call()]))
    c = TestClient(app)
    sid = c.post(
        "/api/sessions", json={"workspace": str(tmp_path), "agent_type": "main"}
    ).json()["id"]

    with c.websocket_connect(f"/api/ws/sessions/{sid}") as ws:
        ws.send_json({"last_seq": 0})
        c.post(f"/api/sessions/{sid}/messages", json={"content": "跑个命令", "model": "mock/mock-model"})
        req_id = None
        for _ in range(40):
            ev = ws.receive_json()
            if ev["type"] == "approval.requested":
                req_id = ev["payload"]["request_id"]
                break
        assert req_id
        # 阻塞期间会话处于 waiting
        assert c.get(f"/api/sessions/{sid}").json()["status"] == "waiting"
        # 决议 allow → 继续执行
        r = c.post(
            f"/api/sessions/{sid}/approvals/{req_id}", json={"decision": "allow"}
        )
        assert r.status_code == 200
        types = []
        for _ in range(40):
            ev = ws.receive_json()
            types.append(ev["type"])
            if ev["type"] == "session.status" and ev["payload"]["status"] == "idle":
                break
        assert "approval.resolved" in types
        assert "tool.result" in types


def test_approval_deny_blocks_tool(tmp_path):
    app = create_app(_client_with_scripted("完成", [_shell_tool_call()]))
    c = TestClient(app)
    sid = c.post(
        "/api/sessions", json={"workspace": str(tmp_path), "agent_type": "main"}
    ).json()["id"]

    with c.websocket_connect(f"/api/ws/sessions/{sid}") as ws:
        ws.send_json({"last_seq": 0})
        c.post(f"/api/sessions/{sid}/messages", json={"content": "跑个命令", "model": "mock/mock-model"})
        req_id = None
        for _ in range(40):
            ev = ws.receive_json()
            if ev["type"] == "approval.requested":
                req_id = ev["payload"]["request_id"]
                break
        c.post(f"/api/sessions/{sid}/approvals/{req_id}", json={"decision": "deny"})
        types = []
        for _ in range(40):
            ev = ws.receive_json()
            types.append(ev["type"])
            if ev["type"] == "session.status" and ev["payload"]["status"] == "idle":
                break
        assert "tool.error" in types  # 被拒绝 → 工具报错


def test_workspace_rename_and_delete(tmp_path):
    app = create_app(_client_with_scripted())
    c = TestClient(app)
    sid = c.post("/api/sessions", json={"workspace": str(tmp_path / "w1")}).json()["id"]
    ws_id = next(
        w["id"] for w in c.get("/api/workspaces").json() if any(s["id"] == sid for s in w["sessions"])
    )
    r = c.post(f"/api/workspaces/{ws_id}/rename", json={"name": "renamed"})
    assert r.status_code == 200
    new_id = r.json()["id"]
    assert new_id.startswith("renamed_")
    # 重命名后旧目录消失、新目录存在
    assert not (paths.workspaces_dir() / ws_id).exists()
    assert (paths.workspaces_dir() / new_id).exists()
    # 删除工作区
    assert c.delete(f"/api/workspaces/{new_id}").status_code == 204
    assert not (paths.workspaces_dir() / new_id).exists()


def test_session_title_generated_after_first_turn(tmp_path):
    """首轮结束后：配置式 summarizer agent 生成标题，并落盘 meta.json。"""
    app = create_app(_client_with_scripted("你好呀"))
    c = TestClient(app)
    sid = c.post("/api/sessions", json={"workspace": str(tmp_path)}).json()["id"]
    assert c.get(f"/api/sessions/{sid}").json()["title"] == ""
    c.post(f"/api/sessions/{sid}/messages", json={"content": "帮我写一个脚本", "model": "mock/mock-model"})

    title = ""
    for _ in range(40):
        s = c.get(f"/api/sessions/{sid}").json()
        if s["title"]:
            title = s["title"]
            break
        time.sleep(0.1)
    assert title  # 标题非空（mock 固定回复 "你好呀"）
    # 标题持久化：meta.json 存在且含 title
    meta = paths.session_meta_path(str(tmp_path), sid)
    assert meta.exists()
    assert json.loads(meta.read_text(encoding="utf-8"))["title"] == title
    # 工作区列表返回标题
    ws = next(w for w in c.get("/api/workspaces").json() if any(s["id"] == sid for s in w["sessions"]))
    assert next(s["title"] for s in ws["sessions"] if s["id"] == sid) == title


def test_quota_reject_when_full(tmp_path):
    # 覆盖全局配置：max=1、不排队 → 第二个并发请求被拒绝
    gdir = seed_global_config()
    (gdir / "mira.toml").write_text(
        "[session]\nmax_concurrent_sessions = 1\nqueue_on_quota = false\n",
        encoding="utf-8",
    )
    app = create_app(_client_with_scripted("完成", [_shell_tool_call()]))
    c = TestClient(app)
    s1 = c.post("/api/sessions", json={"workspace": str(tmp_path / "w1")}).json()["id"]
    s2 = c.post("/api/sessions", json={"workspace": str(tmp_path / "w2")}).json()["id"]

    with c.websocket_connect(f"/api/ws/sessions/{s1}") as ws:
        ws.send_json({"last_seq": 0})
        c.post(f"/api/sessions/{s1}/messages", json={"content": "跑个命令", "model": "mock/mock-model"})
        for _ in range(40):  # 等 s1 进入审批（占住配额）
            ev = ws.receive_json()
            if ev["type"] == "approval.requested":
                break
        # s2 并发 → 拒绝（accepted=False，未启动线程）
        r2 = c.post(f"/api/sessions/{s2}/messages", json={"content": "hi", "model": "mock/mock-model"})
        assert r2.json()["accepted"] is False
        events2 = c.get(f"/api/sessions/{s2}/events").json()
        assert any(e["type"] == "error.raised" for e in events2)
        # 释放 s1
        req_id = c.get(f"/api/sessions/{s1}/approvals").json()[0]["id"]
        c.post(f"/api/sessions/{s1}/approvals/{req_id}", json={"decision": "allow"})


def _poll_events(c, sid, start_seq=0, timeout=40):
    """轮询事件快照直到出现 idle（或超时），返回 (快照, 结束 seq)。"""
    for _ in range(timeout):
        evs = c.get(f"/api/sessions/{sid}/events").json()
        new = [e for e in evs if e["seq"] > start_seq]
        if any(
            e["type"] == "session.status" and e["payload"]["status"] == "idle"
            for e in new
        ):
            return evs, len(evs)
        time.sleep(0.1)
    raise AssertionError("timeout waiting idle")


def test_insert_message_interrupt_and_queue(tmp_path):
    """运行中插入消息：interrupt 插队斧正（最优先），其余排队 FIFO 串行。"""

    class SlowMock(MockProvider):
        def stream_chat(self, messages, **kw):
            time.sleep(0.3)  # 放慢以制造「正在回复」窗口
            yield from super().stream_chat(messages, **kw)

    router = ProviderRouter([SlowMock(id="mock", reply="ok")])
    app = create_app(AppClient(SessionManager(router=router)))
    c = TestClient(app)
    sid = c.post(
        "/api/sessions", json={"workspace": str(tmp_path), "model": "mock/mock-model"}
    ).json()["id"]

    c.post(f"/api/sessions/{sid}/messages", json={"content": "A", "model": "mock/mock-model"})
    # 运行中排队两条 + 插队一条斧正
    c.post(f"/api/sessions/{sid}/insert", json={"content": "A2", "model": "mock/mock-model", "interrupt": False})
    c.post(f"/api/sessions/{sid}/insert", json={"content": "B2", "model": "mock/mock-model", "interrupt": False})
    c.post(f"/api/sessions/{sid}/insert", json={"content": "X", "model": "mock/mock-model", "interrupt": True})

    # 等待全部处理完成（idle 且事件稳定）
    end = time.time() + 15
    users = []
    while time.time() < end:
        evs = c.get(f"/api/sessions/{sid}/events").json()
        users = [e["payload"]["content"] for e in evs if e["type"] == "user.message"]
        latest = [e for e in evs if e["type"] == "session.status"][-1]["payload"]["status"]
        if latest == "idle" and users.count("X") >= 1 and users.count("A2") >= 1 and users.count("B2") >= 1:
            time.sleep(0.6)  # 确保串行链全部收尾
            evs = c.get(f"/api/sessions/{sid}/events").json()
            users = [e["payload"]["content"] for e in evs if e["type"] == "user.message"]
            break
        time.sleep(0.2)

    # 顺序：首轮 A → 斧正 X（插队优先）→ 排队 A2、B2（FIFO）
    assert users[:4] == ["A", "X", "A2", "B2"]


def test_per_reply_model(tmp_path):
    """决策 #25：同一会话每 turn 可换模型；llm.request 记录本轮模型，session.model 同步。"""
    app = create_app(_client_with_scripted("搞定"))
    c = TestClient(app)
    sid = c.post(
        "/api/sessions", json={"workspace": str(tmp_path), "model": "mock/mock-model"}
    ).json()["id"]

    # turn 1：指定 mock 唯一模型（排除标题生成 one_shot 的 task 事件）
    c.post(f"/api/sessions/{sid}/messages", json={"content": "第一轮", "model": "mock/mock-model"})
    evs1, seq1 = _poll_events(c, sid)
    req1 = [
        e for e in evs1 if e["type"] == "llm.request" and "task" not in e["payload"]
    ]
    assert req1 and req1[-1]["payload"]["model"] == "mock-model"

    # turn 2：继续使用 mock 唯一模型
    c.post(f"/api/sessions/{sid}/messages", json={"content": "第二轮", "model": "mock/mock-model"})
    evs2, _ = _poll_events(c, sid, start_seq=seq1)
    req2 = [
        e
        for e in evs2
        if e["seq"] > seq1
        and e["type"] == "llm.request"
        and "task" not in e["payload"]
    ]
    assert req2 and req2[-1]["payload"]["model"] == "mock-model"

    # 决策 #25：session 不绑定 model —— session.model 保持创建时的默认值（每回复模型由请求携带）
    assert c.get(f"/api/sessions/{sid}").json()["model"] == "mock/mock-model"


def test_config_save_reload_registers_new_agent(tmp_path):
    """配置中心保存新增 agent → 热重载 → 新会话主 agent 的 dispatch_task 可选目标包含新 agent。"""
    client = _client_with_scripted()
    manager = client.manager
    main = manager._agents.get("main")
    before = {d["id"] for d in manager._dispatchable_agents(main)}
    assert "new-helper" not in before

    # 模拟配置中心保存 agents 分区（写全局 ~/.mira-code/configs/agents/ 并热重载）
    existing = manager.store.raw_agents()  # 跨层收集的原始 agent dict（无 None，可 TOML 序列化）
    existing.append(
        {
            "id": "new-helper",
            "role": "sub",
            "name": "新助手",
            "description": "测试新增的助手 agent",
            "dispatch": "auto",
        }
    )
    manager.update_config("agents", {"agents": existing})

    # 热重载后 registry 已含新 agent，且在主 agent 的可分派列表里
    assert manager._agents.has("new-helper")
    after = {d["id"] for d in manager._dispatchable_agents(main)}
    assert "new-helper" in after

    # 新会话的主 agent runtime：dispatch_task 工具可用目标包含新 agent
    sess = manager.create_session(tmp_path, agent_type="main")
    rt = manager._build_runtime(sess)
    dt = rt.tools.get("dispatch_task")
    avail = [a["id"] for a in dt._available]
    assert "new-helper" in avail


def test_observe_page_served_and_isolated():
    """遥测观测页（/observe）：独立页面 + 静态资源可访问，与主页面互相无跳转入口。"""
    app = create_app(_client_with_scripted())
    c = TestClient(app)

    r = c.get("/observe")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "observe.js" in r.text
    assert "observe.css" in r.text

    # 静态资源
    assert c.get("/static/observe.js").status_code == 200
    assert c.get("/static/observe.css").status_code == 200

    # 隔离：观测页不加载主 SPA（app.js）；主页不引用 /observe（无跳转按钮）
    assert "app.js" not in r.text
    assert "/observe" not in c.get("/").text
