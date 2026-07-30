import json
from pathlib import Path

from nano_claude.core import diff_service


def test_list_checkpoints_for_session_supports_legacy_diff_filename(tmp_path, monkeypatch):
    checkpoint_name = "2026-01-01T00-00-00-abcdef01.json"
    mapping_path = tmp_path / "mapping.json"
    checkpoint_path = tmp_path / checkpoint_name

    mapping_path.write_text(
        json.dumps(
            {
                "version": 1,
                "mappings": [
                    {
                        "segment_key": "seg-1",
                        "diff_filename": checkpoint_name,
                        "session_file": "session-1.json",
                        "timestamp": "2026-01-01T00-00-00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    checkpoint_path.write_text(
        json.dumps(
            {
                "summary": {"files_changed": 1},
                "files": {"modified": {"a.py": "before"}, "deleted": {}, "added": [], "binary": []},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(diff_service, "get_diff_dir", lambda _cwd: str(tmp_path))

    result = diff_service.list_checkpoints_for_session("/repo", "session-1.json")

    assert len(result) == 1
    assert result[0]["checkpoint_filename"] == checkpoint_name
    assert result[0]["summary"]["files_changed"] == 1
    assert result[0]["summary"]["files"] == [{"path": "a.py", "status": "modified"}]

    saved_mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    assert saved_mapping["version"] == 2
    assert saved_mapping["mappings"][0]["checkpoint_filename"] == checkpoint_name


def test_get_checkpoint_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(diff_service, "get_diff_dir", lambda _cwd: str(tmp_path))
    assert diff_service.get_checkpoint("/repo", "../secrets.json") is None
