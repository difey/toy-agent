"""P1：工具层单测（shell / file / search / permission / 截断 / 超时）。"""

import time
from pathlib import Path

import pytest

from mira import paths
from mira.core.config.schemas import ApprovalMode, PermissionRule
from mira.core.tools.base import Tool, ToolContext, ToolResult, truncate_output
from mira.core.tools.permission import PermissionAction, PermissionChecker
from mira.core.tools.registry import ToolRegistry


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(workspace=tmp_path, session_id="s1")


def test_shell_echo(tmp_path):
    tool = ToolRegistry.with_builtins().get("shell")
    res = tool.run(_ctx(tmp_path), cmd="echo hello")
    assert res.ok
    assert "hello" in res.output
    assert res.duration_ms >= 0


def test_shell_failure(tmp_path):
    tool = ToolRegistry.with_builtins().get("shell")
    res = tool.run(_ctx(tmp_path), cmd="exit 3")
    assert not res.ok
    assert "exit=3" in (res.error or "")


def test_file_write_read_edit(tmp_path):
    reg = ToolRegistry.with_builtins()
    write = reg.get("file_write")
    read = reg.get("file_read")
    edit = reg.get("file_edit")

    r = write.run(_ctx(tmp_path), path="a/b.txt", content="line1\nline2\n")
    assert r.ok

    r = read.run(_ctx(tmp_path), path="a/b.txt")
    assert r.ok and "line1" in r.output

    r = edit.run(_ctx(tmp_path), path="a/b.txt", old="line1", new="CHANGED")
    assert r.ok
    assert (tmp_path / "a/b.txt").read_text().startswith("CHANGED")


def test_file_edit_anchor_missing(tmp_path):
    (tmp_path / "x.txt").write_text("hello", encoding="utf-8")
    tool = ToolRegistry.with_builtins().get("file_edit")
    res = tool.run(_ctx(tmp_path), path="x.txt", old="nope", new="y")
    assert not res.ok


def test_search_grep(tmp_path):
    (tmp_path / "main.py").write_text("def hello():\n    pass\n", encoding="utf-8")
    tool = ToolRegistry.with_builtins().get("search_grep")
    res = tool.run(_ctx(tmp_path), pattern="def hello")
    assert res.ok
    assert "main.py:1" in res.output


def test_truncate_output():
    truncated, out = truncate_output("x" * 100, max_len=50)
    assert truncated
    assert out.startswith("x" * 50)
    assert "截断" in out
    truncated, out = truncate_output("short")
    assert not truncated


def test_tool_invoke_with_timeout():
    """决策：每个工具可单独配置 timeout_s，invoke 时生效（超时返回 ok=False）。"""

    class SlowTool(Tool):
        name = "slow_tool"
        timeout_s = 0.2

        def run(self, ctx, **args):
            time.sleep(2)
            return ToolResult(ok=True, output="done")

    res = SlowTool().invoke(ToolContext(), cmd="sleep 2", note="重活")
    assert not res.ok
    assert "超时" in (res.error or "")
    assert "slow_tool" in (res.error or "")  # 失败信息含工具名
    assert "sleep 2" in (res.error or "")  # 与参数
    assert res.duration_ms >= 200


def test_tool_invoke_within_timeout():
    class FastTool(Tool):
        name = "fast_tool"
        timeout_s = 5

        def run(self, ctx, **args):
            return ToolResult(ok=True, output="ok")

    res = FastTool().invoke(ToolContext())
    assert res.ok
    assert res.output == "ok"


def test_tool_invoke_reraises_error():
    class BoomTool(Tool):
        name = "boom_tool"
        timeout_s = 5

        def run(self, ctx, **args):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        BoomTool().invoke(ToolContext())


def test_shell_default_timeout():
    tool = ToolRegistry.with_builtins().get("shell")
    assert tool.timeout_s == 60
    # 名称已统一为下划线（LLM provider 不支持 `.`）
    assert set(ToolRegistry.with_builtins().names()) == {
        "shell", "file_read", "file_write", "file_edit", "search_grep",
        "glob", "todowrite", "apply_patch", "project_memory", "web_fetch", "web_search",
        "attach_image", "skill",
    }


def test_glob_tool(tmp_path):
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.py").write_text("y", encoding="utf-8")
    (tmp_path / "c.txt").write_text("z", encoding="utf-8")
    tool = ToolRegistry.with_builtins().get("glob")
    res = tool.run(_ctx(tmp_path), pattern="**/*.py")
    assert res.ok
    assert "a.py" in res.output
    assert "sub/b.py" in res.output
    assert "c.txt" not in res.output
    res = tool.run(_ctx(tmp_path), pattern="**/*.nope")
    assert res.ok and "no matches" in res.output


def test_todowrite_roundtrip(tmp_path):
    tool = ToolRegistry.with_builtins().get("todowrite")
    todos = [
        {"content": "调研", "status": "in_progress", "priority": "high"},
        {"content": "实现", "status": "pending", "priority": "medium"},
    ]
    res = tool.run(_ctx(tmp_path), todos=todos)
    assert res.ok
    assert "in_progress" in res.output
    # 写入当前 session 自己的目录（会话隔离）
    store = paths.session_dir(tmp_path, "s1") / "todos.json"
    assert store.exists()
    assert "调研" in store.read_text(encoding="utf-8")
    # 非法状态被拒绝
    res = tool.run(_ctx(tmp_path), todos=[{"content": "x", "status": "nope", "priority": "high"}])
    assert not res.ok


def test_apply_patch_add_update_delete(tmp_path):
    tool = ToolRegistry.with_builtins().get("apply_patch")
    patch = (
        "*** Add File: new.txt\n"
        "+line1\n"
        "+line2\n"
        "*** Update File: new.txt\n"
        "@@ -1,2 +1,2 @@\n"
        "-line1\n"
        "+CHANGED\n"
        " line2\n"
    )
    res = tool.run(_ctx(tmp_path), patchText=patch)
    assert res.ok, res.error
    assert "A new.txt" in res.output
    assert "U new.txt" in res.output
    assert (tmp_path / "new.txt").read_text() == "CHANGED\nline2"
    # delete
    res = tool.run(_ctx(tmp_path), patchText="*** Delete File: new.txt\n")
    assert res.ok
    assert not (tmp_path / "new.txt").exists()


def test_web_fetch_invalid_url():
    tool = ToolRegistry.with_builtins().get("web_fetch")
    res = tool.run(ToolContext(), url="not-a-url")
    assert not res.ok
    assert "http" in (res.error or "")


def test_web_search_missing_query():
    tool = ToolRegistry.with_builtins().get("web_search")
    assert tool.timeout_s == 30
    res = tool.run(ToolContext())
    assert not res.ok
    assert "query" in (res.error or "")
    res = tool.run(ToolContext(), query="   ")
    assert not res.ok


def test_web_search_ok_with_query(monkeypatch):
    """回归：web_search 正常调用不应报 _call_exa() got multiple values for 'query'。"""
    import mira.core.tools.builtin.websearch as ws_module

    monkeypatch.setattr(ws_module, "_call_exa", lambda query, **opts: "dflash2 搜索结果")
    tool = ToolRegistry.with_builtins().get("web_search")
    res = tool.run(ToolContext(), query="dflash2", numResults=3)
    assert res.ok
    assert "dflash2 搜索结果" in res.output


def test_permission_checker():
    rules = [
        PermissionRule(tool="shell_*", path="**", action="ask"),
        PermissionRule(tool="file_read", path="**", action="allow"),
    ]
    checker = PermissionChecker(rules, mode=ApprovalMode.ASK)
    assert checker.check("shell_run") == PermissionAction.ASK
    assert checker.check("file_read") == PermissionAction.ALLOW
    assert checker.check("file_write") == PermissionAction.ALLOW  # 未命中默认允许

    assert PermissionChecker(rules, mode=ApprovalMode.AUTO).check("shell_run") == PermissionAction.ASK
    # deny 模式只影响 ask 解析：显式 allow 仍放行；ask（shell_*）被拒绝
    assert PermissionChecker(rules, mode=ApprovalMode.DENY).check("file_read") == PermissionAction.ALLOW
    assert PermissionChecker(rules, mode=ApprovalMode.DENY).check("shell_run") == PermissionAction.DENY


def test_registry_enabled_skips_missing():
    reg = ToolRegistry.with_builtins()
    enabled = reg.enabled(["file_read", "not-a-tool"])
    assert [t.name for t in enabled] == ["file_read"]
    assert reg.missing(["file_read", "not-a-tool"]) == ["not-a-tool"]


def test_attach_image_validation(tmp_path):
    """attach_image：缺路径 / 非图片 / 文件不存在 均报错。"""
    tool = ToolRegistry.with_builtins().get("attach_image")
    assert tool is not None
    # 缺路径
    r = tool.run(_ctx(tmp_path))
    assert not r.ok and "path" in r.error
    # 文件不存在
    r = tool.run(_ctx(tmp_path), path=str(tmp_path / "no.png"))
    assert not r.ok and "不存在" in r.error
    # 非图片扩展名
    txt = tmp_path / "a.txt"
    txt.write_text("x", encoding="utf-8")
    r = tool.run(_ctx(tmp_path), path=str(txt))
    assert not r.ok and "不支持的图片格式" in r.error


def test_attach_image_calls_hook(tmp_path):
    """attach_image：图片存在时调用 meta 钩子并把绝对路径传入。"""
    tool = ToolRegistry.with_builtins().get("attach_image")
    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfakedata")
    calls: list[str] = []
    ctx = ToolContext(workspace=tmp_path, session_id="s1", meta={"attach_image": calls.append})
    r = tool.run(ctx, path=str(img))
    assert r.ok and "已加入上下文" in r.output
    assert calls == [str(img)]


def test_attach_image_missing_hook(tmp_path):
    tool = ToolRegistry.with_builtins().get("attach_image")
    img = tmp_path / "shot.png"
    img.write_bytes(b"x")
    r = tool.run(_ctx(tmp_path), path=str(img))  # 无 attach_image 钩子
    assert not r.ok and "钩子" in r.error
