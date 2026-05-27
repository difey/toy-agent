"""Tests for the sub-agent bash command review module."""
import sys
import os
import tempfile
import shutil

# Ensure src is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from nano_claude.tools.bash_review import (
    BashReviewResult,
    is_harmless_command,
    detect_external_dir_operation,
    gather_project_context,
    _parse_review_json,
)
from nano_claude.tools.bash import REVIEW_TIMEOUT


def test_imports():
    assert BashReviewResult is not None
    assert REVIEW_TIMEOUT == 15


def test_is_harmless_command():
    assert is_harmless_command("ls -la") is True
    assert is_harmless_command("echo hello") is True
    assert is_harmless_command("pwd") is True
    assert is_harmless_command("cd src") is True
    assert is_harmless_command("which python") is True
    # Non-harmless commands
    assert is_harmless_command("pip install flask") is False
    assert is_harmless_command("rm -rf /") is False
    assert is_harmless_command("python script.py") is False
    print("  ✓ is_harmless_command")


def test_detect_external_dir_operation():
    tmpdir = tempfile.mkdtemp()
    try:
        # Same directory → False
        assert detect_external_dir_operation("ls", tmpdir, tmpdir) is False
        # Different workdir → True
        assert detect_external_dir_operation("ls", tmpdir, "/etc") is True
        # Parent traversal → True
        assert detect_external_dir_operation("rm ../file", tmpdir, tmpdir) is True
        # Absolute path outside cwd → True
        assert detect_external_dir_operation("cat /etc/passwd", tmpdir, tmpdir) is True
        # Absolute path inside cwd → False
        inner = os.path.join(tmpdir, "subdir")
        assert detect_external_dir_operation("cat /etc/passwd", tmpdir, tmpdir) is True
    finally:
        shutil.rmtree(tmpdir)
    print("  ✓ detect_external_dir_operation")


def test_gather_project_context():
    ctx = gather_project_context(".")
    assert "Top-level entries" in ctx
    assert len(ctx) > 10
    print("  ✓ gather_project_context")


def test_parse_review_json_bare():
    r = _parse_review_json(
        '{"verdict": "safe", "summary": "test", "risk_description": "", '
        '"affected_paths": [], "recommendation": ""}'
    )
    assert r is not None
    assert r.verdict == "safe"
    assert r.summary == "test"
    print("  ✓ parse_review_json (bare)")


def test_parse_review_json_fence():
    r = _parse_review_json(
        '```json\n{"verdict": "dangerous", "summary": "rm root", '
        '"risk_description": "deletes everything", "affected_paths": ["/"], '
        '"recommendation": "deny"}\n```'
    )
    assert r is not None
    assert r.verdict == "dangerous"
    assert r.summary == "rm root"
    print("  ✓ parse_review_json (fence)")


def test_parse_review_json_invalid():
    r = _parse_review_json("not json at all")
    assert r is None
    r = _parse_review_json('{"verdict": "unknown"}')
    assert r is not None
    assert r.verdict == "suspicious"
    print("  ✓ parse_review_json (invalid/fallback)")


def test_parse_review_json_missing_fields():
    r = _parse_review_json('{"verdict": "safe"}')
    assert r is not None
    assert r.verdict == "safe"
    assert r.summary == ""
    assert r.risk_description == ""
    print("  ✓ parse_review_json (missing fields)")


if __name__ == "__main__":
    test_imports()
    test_is_harmless_command()
    test_detect_external_dir_operation()
    test_gather_project_context()
    test_parse_review_json_bare()
    test_parse_review_json_fence()
    test_parse_review_json_invalid()
    test_parse_review_json_missing_fields()
    print("\n✓ All tests passed!")
