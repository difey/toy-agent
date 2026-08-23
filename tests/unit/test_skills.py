"""Skills 文件来源：SKILL.md 解析 / 目录扫描 / 合并 / system prompt 注入。"""

from __future__ import annotations

from pathlib import Path

from mira.core.agents.base import BaseAgent
from mira.core.config.schemas import AgentConfig, AgentRole, AgentSkillsConfig, SkillConfig
from mira.core.skills.loader import SkillLoader, parse_skill_file, scan_skill_dir
from mira.core.skills.registry import SkillRegistry
from mira.core.tools.base import ToolContext
from mira.core.tools.builtin.skill import SkillTool


def _write_skill_dir(root: Path, name: str, body: str, fm: str | None = None) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    text = ""
    if fm is not None:
        text = "---\n" + fm.strip("\n") + "\n---\n\n"
    (d / "SKILL.md").write_text(text + body, encoding="utf-8")
    return d / "SKILL.md"


def test_parse_skill_file_directory_form(tmp_path):
    """目录形式 SKILL.md：frontmatter + body 解析为 Skill。"""
    p = _write_skill_dir(
        tmp_path,
        "code-style",
        "Please follow:\n- 2-space indent\n- camelCase\n",
        fm="name: code-style\ndescription: Code style guidelines\ntype: prompt\nwhenToUse: when writing code",
    )
    skill = parse_skill_file(p)
    assert skill is not None
    assert skill.id == "code-style"
    assert skill.name == "code-style"
    assert skill.description == "Code style guidelines"
    assert "2-space indent" in skill.prompt
    assert "Please follow" in skill.prompt


def test_parse_skill_file_flow_skipped(tmp_path):
    """type=flow 的技能不可自动调用，跳过。"""
    p = _write_skill_dir(tmp_path, "manual", "some body", fm="name: manual\ndescription: x\ntype: flow")
    assert parse_skill_file(p) is None


def test_parse_skill_file_no_frontmatter(tmp_path):
    """无 frontmatter 的 .md：整篇当指令，文件名作 id。"""
    f = tmp_path / "plain.md"
    f.write_text("直接指令文本", encoding="utf-8")
    skill = parse_skill_file(f)
    assert skill is not None and skill.id == "plain"
    assert skill.prompt == "直接指令文本"
    assert skill.description  # 首行


def test_parse_skill_file_tools_frontmatter(tmp_path):
    """frontmatter 的 tools 列表解析进 Skill.tools。"""
    p = _write_skill_dir(
        tmp_path,
        "code-style",
        "some body",
        fm="name: code-style\ndescription: style\ntype: prompt\ntools:\n- file_read\n- grep_search",
    )
    skill = parse_skill_file(p)
    assert skill is not None
    assert skill.tools == ["file_read", "grep_search"]


def test_scan_skill_dir_forms_and_priority(tmp_path):
    """目录形式优先；平面形式兜底；同 id 目录覆盖平面。"""
    _write_skill_dir(tmp_path, "planning", "dir version prompt", fm="name: planning\ndescription: p")
    flat = tmp_path / "code-exploration.md"
    flat.write_text("flat prompt", encoding="utf-8")
    # 同名平面文件：目录形式优先
    dup = tmp_path / "planning.md"
    dup.write_text("flat dup", encoding="utf-8")
    skills = scan_skill_dir(tmp_path)
    assert "planning" in skills and "code-exploration" in skills
    assert skills["planning"].prompt == "dir version prompt"
    assert skills["code-exploration"].prompt == "flat prompt"


def test_build_merges_configs_and_dirs(tmp_path):
    """SkillLoader.build：toml 技能 + 文件目录技能合并，文件目录覆盖同名。"""
    cfgs = {"planning": SkillConfig(id="planning", name="计划", prompt="toml 版")}
    d1 = tmp_path / "d1"
    d1.mkdir()
    _write_skill_dir(d1, "planning", "dir 版 prompt", fm="name: planning\ndescription: p")
    _write_skill_dir(d1, "newskill", "新技能", fm="name: newskill\ndescription: n")
    reg = SkillLoader.build(cfgs, [d1])
    assert reg.get("planning") is not None
    assert reg.get("planning").prompt == "dir 版 prompt"  # 文件覆盖 toml
    assert reg.get("newskill") is not None


def test_skill_index_injected_into_system_prompt(tmp_path):
    """compose_system_prompt 只列启用技能的 description 索引，全文不注入（按需经 skill 工具取）。"""
    d = tmp_path / "skills"
    d.mkdir()
    _write_skill_dir(d, "code-style", "Use 2-space indent.", fm="name: code-style\ndescription: style")
    reg = SkillRegistry().register_many(list(scan_skill_dir(d).values()))
    agent = BaseAgent(
        AgentConfig(
            id="main",
            role=AgentRole.MAIN,
            system_prompt="你是助手。",
            skills=AgentSkillsConfig(enabled=["code-style"]),
            model="mock/m",
        )
    )
    sp = agent.compose_system_prompt(reg)
    assert sp.startswith("你是助手。")
    assert "[可用技能]" in sp
    assert "code-style: style" in sp  # 只列 id + description
    assert "Use 2-space indent." not in sp  # 全文不再注入 system prompt


def test_skill_tool_returns_full_text(tmp_path):
    """skill 工具：传入技能名 → 返回该技能全文作为 tool result。"""
    d = tmp_path / "skills"
    d.mkdir()
    _write_skill_dir(d, "code-style", "Use 2-space indent.", fm="name: code-style\ndescription: style")
    reg = SkillRegistry().register_many(list(scan_skill_dir(d).values()))
    tool = SkillTool()
    r = tool.run(
        ToolContext(workspace=tmp_path, meta={"skill_lookup": lambda n: reg.get(n)}),
        name="code-style",
    )
    assert r.ok
    assert "Use 2-space indent." in r.output
    assert "style" in r.output


def test_skill_tool_unknown_name():
    """skill 工具：未知技能名报错。"""
    tool = SkillTool()
    r = tool.run(ToolContext(meta={"skill_lookup": lambda n: None}), name="nope")
    assert not r.ok
    assert "未找到技能" in r.error


def test_skill_tool_missing_hook():
    """skill 工具：无 skill_lookup 钩子报错（须在运行时执行）。"""
    tool = SkillTool()
    r = tool.run(ToolContext(), name="planning")
    assert not r.ok
    assert "skill_lookup" in r.error
