"""project_memory 工具单测：read / append / replace / 路径隔离。

记忆文件位于 workspace 数据目录（MIRA_HOME 已由 conftest 隔离到临时目录）：
    ~/.mira-code/workspaces/<ws_id>/memory.md
"""

from __future__ import annotations

from mira import paths
from mira.core.tools.base import ToolContext
from mira.core.tools.registry import ToolRegistry


def _ws(tmp_path, name="proj"):
    p = tmp_path / name
    p.mkdir(exist_ok=True)
    return p


def _ctx(ws) -> ToolContext:
    return ToolContext(workspace=ws, session_id="s1")


def _mem(ws) -> "object":
    return paths.workspace_dir(ws) / "memory.md"


def _tool():
    return ToolRegistry.with_builtins().get("project_memory")


def test_registered_in_builtins():
    assert _tool() is not None


def test_read_empty_when_missing(tmp_path):
    ws = _ws(tmp_path)
    res = _tool().run(_ctx(ws), operation="read")
    assert res.ok
    assert "尚无" in res.output


def test_append_creates_file(tmp_path):
    ws = _ws(tmp_path)
    res = _tool().run(_ctx(ws), operation="append", content="项目用 uv 管理依赖")
    assert res.ok
    p = _mem(ws)
    assert p.exists()
    assert "uv" in p.read_text(encoding="utf-8")


def test_append_accumulates(tmp_path):
    ws = _ws(tmp_path)
    tool = _tool()
    assert tool.run(_ctx(ws), operation="append", content="第一条").ok
    assert tool.run(_ctx(ws), operation="append", content="第二条").ok
    text = _mem(ws).read_text(encoding="utf-8")
    assert "第一条" in text
    assert "第二条" in text


def test_append_empty_content_fails(tmp_path):
    ws = _ws(tmp_path)
    res = _tool().run(_ctx(ws), operation="append", content="")
    assert not res.ok


def test_replace_exact(tmp_path):
    ws = _ws(tmp_path)
    tool = _tool()
    tool.run(_ctx(ws), operation="append", content="alpha beta")
    res = tool.run(_ctx(ws), operation="replace", old_text="beta", content="gamma")
    assert res.ok
    text = _mem(ws).read_text(encoding="utf-8")
    assert "alpha gamma" in text
    assert "beta" not in text


def test_replace_missing_anchor_fails(tmp_path):
    ws = _ws(tmp_path)
    tool = _tool()
    tool.run(_ctx(ws), operation="append", content="hello world")
    res = tool.run(_ctx(ws), operation="replace", old_text="nope", content="x")
    assert not res.ok


def test_replace_ambiguous_anchor_fails(tmp_path):
    ws = _ws(tmp_path)
    tool = _tool()
    tool.run(_ctx(ws), operation="append", content="abc abc")
    res = tool.run(_ctx(ws), operation="replace", old_text="abc", content="x")
    assert not res.ok


def test_replace_overwrite_when_no_anchor(tmp_path):
    ws = _ws(tmp_path)
    tool = _tool()
    tool.run(_ctx(ws), operation="append", content="旧内容")
    res = tool.run(_ctx(ws), operation="replace", old_text="", content="全新内容")
    assert res.ok
    assert _mem(ws).read_text(encoding="utf-8") == "全新内容\n"


def test_isolated_per_workspace(tmp_path):
    wa, wb = _ws(tmp_path, "a"), _ws(tmp_path, "b")
    tool = _tool()
    tool.run(_ctx(wa), operation="append", content="A 的记忆")
    tool.run(_ctx(wb), operation="append", content="B 的记忆")
    assert "A 的记忆" in _mem(wa).read_text(encoding="utf-8")
    assert "A 的记忆" not in _mem(wb).read_text(encoding="utf-8")
    assert paths.workspace_dir(wa) != paths.workspace_dir(wb)
