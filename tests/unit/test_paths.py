"""P0：~/.mira-code/ 数据布局单测（mira.paths）。"""

from mira import paths


def test_layout(monkeypatch, tmp_path):
    home = tmp_path / ".mira-code"
    monkeypatch.setenv("MIRA_HOME", str(home))
    # 全局配置：数据根目录顶层
    assert paths.global_config_dir() == home / "configs"
    # workspace 层：workspaces/ 下，名称为 {文件夹名}_{全路径哈希}
    ws = "/home/user/workspace"
    ws_dir = paths.workspace_dir(ws)
    assert ws_dir.parent == home / "workspaces"
    name, _, tail = ws_dir.name.partition("_")
    assert name == "workspace"
    assert len(tail) == 7  # 短哈希
    # session 层：sessions/<session_hashcode>/session_id.jsonl
    sid = "a1b2c3d4e5"
    assert paths.session_dir(ws, sid) == ws_dir / "sessions" / sid
    assert (
        paths.session_log_path(ws, sid) == ws_dir / "sessions" / sid / "session_id.jsonl"
    )
    assert (
        paths.session_reports_dir(ws, sid) == ws_dir / "sessions" / sid / "reports"
    )
    # workspace 级遥测
    assert paths.telemetry_dir(ws) == ws_dir / "telemetry"
    assert paths.sqlite_path(ws) == ws_dir / "telemetry" / "mira.db"


def test_workspace_id_deterministic_and_unique(monkeypatch, tmp_path):
    monkeypatch.setenv("MIRA_HOME", str(tmp_path / ".mira-code"))
    a = paths.workspace_id("/home/user/workspace")
    assert a == paths.workspace_id("/home/user/workspace")  # 确定性
    assert a != paths.workspace_id("/other/workspace")  # 不同路径哈希不同
    assert a.startswith("workspace_")
    # 已编码 id 原样返回
    assert paths.workspace_id(a) == a


def test_mira_home_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("MIRA_HOME", str(tmp_path / "custom"))
    assert paths.mira_home() == tmp_path / "custom"
