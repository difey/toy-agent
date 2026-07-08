import pytest

from nano_claude.core.tool_contracts import ToolContext
from nano_claude.tools.skill import SkillStore, SkillTool, build_skills_section


def _write_skill(tmp_path, name, description="", content="Do the thing."):
    skill_dir = tmp_path / name
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n{content}\n"
    )


def test_skill_store_discover_and_list(tmp_path):
    _write_skill(tmp_path, "pdf", description="Work with PDF files.")
    _write_skill(tmp_path, "xlsx", description="Work with spreadsheets.")

    store = SkillStore()
    store.discover([str(tmp_path)])

    assert store.count == 2
    names = [s.name for s in store.list_all()]
    assert names == ["pdf", "xlsx"]


def test_skill_store_get_missing_returns_none(tmp_path):
    store = SkillStore()
    store.discover([str(tmp_path)])
    assert store.get("nonexistent") is None


def test_build_skills_section_empty():
    assert build_skills_section([]) == ""


def test_build_skills_section_lists_names(tmp_path):
    _write_skill(tmp_path, "pdf", description="Work with PDF files.")
    store = SkillStore()
    store.discover([str(tmp_path)])

    section = build_skills_section(store.list_all())
    assert "## Available Skills" in section
    assert "`pdf`" in section
    assert "Work with PDF files." in section


@pytest.mark.asyncio
async def test_skill_tool_no_store_configured(tmp_path):
    tool = SkillTool()
    ctx = ToolContext(cwd=str(tmp_path))
    r = await tool.execute({"name": "pdf"}, ctx)
    assert "No skill store available" in r.output
    assert r.title == "skill [error]"


@pytest.mark.asyncio
async def test_skill_tool_unknown_skill(tmp_path):
    store = SkillStore()
    store.discover([str(tmp_path)])
    tool = SkillTool()
    ctx = ToolContext(cwd=str(tmp_path), skill_store=store)
    r = await tool.execute({"name": "pdf"}, ctx)
    assert "No skills are available" in r.output


@pytest.mark.asyncio
async def test_skill_tool_loads_content(tmp_path):
    _write_skill(tmp_path, "pdf", description="Work with PDF files.", content="Use pdfplumber.")
    store = SkillStore()
    store.discover([str(tmp_path)])

    tool = SkillTool()
    ctx = ToolContext(cwd=str(tmp_path), skill_store=store)
    r = await tool.execute({"name": "pdf"}, ctx)

    assert r.title == "skill [pdf]"
    assert "Use pdfplumber." in r.output
    assert r.metadata["skill_name"] == "pdf"
