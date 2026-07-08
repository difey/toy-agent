from nano_claude.core.path_utils import correct_hallucinated_path, resolve_safe_path
from nano_claude.core.tool_contracts import ToolContext


def test_correct_hallucinated_path_remaps_known_base(tmp_path):
    corrected = correct_hallucinated_path("/workspace/src/foo.py", str(tmp_path))
    assert corrected == str(tmp_path / "src" / "foo.py")


def test_correct_hallucinated_path_leaves_relative_paths_untouched(tmp_path):
    assert correct_hallucinated_path("src/foo.py", str(tmp_path)) == "src/foo.py"


def test_correct_hallucinated_path_leaves_existing_path_within_cwd(tmp_path):
    f = tmp_path / "real.py"
    f.write_text("x")
    assert correct_hallucinated_path(str(f), str(tmp_path)) == str(f)


def test_resolve_safe_path_joins_relative_with_cwd(tmp_path):
    ctx = ToolContext(cwd=str(tmp_path))
    resolved = resolve_safe_path("src/foo.py", ctx)
    assert resolved == str((tmp_path / "src" / "foo.py").resolve())


def test_resolve_safe_path_corrects_hallucinated_base(tmp_path):
    ctx = ToolContext(cwd=str(tmp_path))
    resolved = resolve_safe_path("/project/src/foo.py", ctx)
    assert resolved == str((tmp_path / "src" / "foo.py").resolve())
