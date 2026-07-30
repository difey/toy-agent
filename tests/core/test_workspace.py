from pathlib import Path

from nano_claude.core import workspace


def test_list_plan_docs_and_get_plan_doc(tmp_path, monkeypatch):
    older = tmp_path / "older.md"
    newer = tmp_path / "newer.md.resolved"
    older.write_text("# older", encoding="utf-8")
    newer.write_text("# newer", encoding="utf-8")
    older.touch()
    newer.touch()

    monkeypatch.setattr(workspace, "get_plan_dir", lambda cwd: str(tmp_path))
    monkeypatch.setattr(workspace.os.path, "getmtime", lambda path: 100 if Path(path).name == "older.md" else 200)

    docs = workspace.list_plan_docs("/repo")
    assert [doc["filename"] for doc in docs] == ["newer.md.resolved", "older.md"]

    selected = workspace.get_plan_doc("/repo", "older.md")
    assert selected["exists"] is True
    assert selected["filename"] == "older.md"
    assert selected["content"] == "# older"

    missing = workspace.get_plan_doc("/repo", "../nope.md")
    assert missing["exists"] is False


def test_list_modified_files_parses_git_status(monkeypatch):
    class Result:
        def __init__(self, stdout: str):
            self.stdout = stdout

    calls: list[list[str]] = []

    def fake_run(args, **_kwargs):
        calls.append(args)
        if args[3] == "--show-toplevel":
            return Result("/repo\n")
        return Result(
            " M frontend/src/pages/chat/ChatApp.tsx\n"
            "?? tests/core/test_workspace.py\n"
            "R  old.md -> new.md\n"
            " M docs/space dir/file name.md\n"
        )

    monkeypatch.setattr(workspace.subprocess, "run", fake_run)

    files = workspace.list_modified_files("/repo")

    assert calls[0] == ["git", "-C", "/repo", "rev-parse", "--show-toplevel"]
    assert files == [
        {"path": "frontend/src/pages/chat/ChatApp.tsx", "status": "M"},
        {"path": "tests/core/test_workspace.py", "status": "?"},
        {"path": "new.md", "status": "R"},
        {"path": "docs/space dir/file name.md", "status": "M"},
    ]
