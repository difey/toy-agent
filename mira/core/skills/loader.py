"""SkillLoader：由配置 / SKILL.md 文件构造注册表 + 组合 system prompt 技能索引。

技能来源（兼容 Kimi Code CLI 的 Agent Skills 标准）：
1. configs/skills/（配置层标准 SKILL.md 目录，最低优先级）；
2. ~/.agents/skills/（用户级通用技能，真实 OS home 下、跨工具共享）；
3. ~/.mira-code/skills/（mira 用户级技能，随 MIRA_HOME 重定向）；
4. <workspace>/.skills/（工作目录项目级技能，最高优先级，同名覆盖以上）。

SKILL.md 支持目录形式（<name>/SKILL.md）与平面形式（<name>.md，文件名作 id），
frontmatter（YAML）用轻量手写解析（避免引入 yaml 依赖），覆盖常见字段：
name / description / type / whenToUse / disableModelInvocation / arguments。
"""

from __future__ import annotations

from pathlib import Path

from mira.core.config.schemas import SkillConfig
from mira.core.skills.base import Skill
from mira.core.skills.registry import SkillRegistry


def _split_frontmatter(text: str) -> tuple[dict | None, str]:
    """切分 SKILL.md：返回 (frontmatter dict 或 None, body)。无 frontmatter 时 body=全文。"""
    if not text.startswith("---"):
        return None, text
    end = text.find("\n---", 3)
    if end == -1:
        return None, text
    fm_text = text[3:end].strip()
    body = text[end + 4:].lstrip("\n")
    return _parse_frontmatter(fm_text), body


def _parse_frontmatter(fm_text: str) -> dict:
    """轻量 YAML frontmatter 解析：`key: value` + 列表项（如 arguments: - a - b）。"""
    meta: dict = {}
    lines = fm_text.splitlines()
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("-"):
            i += 1
            continue
        if ":" not in stripped:
            i += 1
            continue
        key, _, raw = lines[i].partition(":")
        key = key.strip()
        val = raw.strip().strip('"').strip("'")
        i += 1
        items: list[str] = []
        while i < len(lines) and lines[i].strip().startswith("-"):
            items.append(lines[i].strip()[1:].strip().strip('"').strip("'"))
            i += 1
        meta[key] = items if items else val
    return meta


def _first_line(text: str, limit: int = 240) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:limit]
    return ""


def parse_skill_file(path: Path, default_id: str | None = None) -> Skill | None:
    """解析单个 SKILL.md（或 .md）文件为 Skill。无法解析 / flow 类型 / 空 body → None。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    fm, body = _split_frontmatter(text)
    body = body.strip()
    if not body:
        return None
    if fm is None:
        # 无 frontmatter：整篇当指令，文件名作 id
        sid = default_id or path.stem
        return Skill(id=sid, name=sid, description=_first_line(body), prompt=body, tools=[])
    name = str(fm.get("name") or "").strip() or (default_id or path.stem)
    stype = str(fm.get("type") or "prompt").strip().lower()
    if stype not in ("prompt", "inline"):
        return None  # flow 等不可自动调用，跳过
    description = str(fm.get("description") or "").strip()
    if not description:
        description = _first_line(body)
    if not name or not description:
        return None  # 目录形式要求 name + description
    tools = fm.get("tools") or []
    if isinstance(tools, str):  # 单值容错
        tools = [tools]
    tools = [str(t).strip() for t in tools if str(t).strip()]
    return Skill(id=name, name=name, description=description, prompt=body, tools=tools)


def scan_skill_dir(root: str | Path) -> dict[str, Skill]:
    """扫描技能目录：目录形式 <name>/SKILL.md 优先，平面形式 <name>.md 兜底。返回 {id: Skill}。"""
    root = Path(root)
    if not root.is_dir():
        return {}
    result: dict[str, Skill] = {}
    # 目录形式
    for d in sorted(root.iterdir()):
        if d.is_dir() and (d / "SKILL.md").is_file():
            skill = parse_skill_file(d / "SKILL.md", d.name)
            if skill:
                result[skill.id] = skill
    # 平面形式（未被目录形式占用）
    for f in sorted(root.iterdir()):
        if f.is_file() and f.suffix.lower() == ".md" and f.name.lower() != "skill.md":
            sid = f.stem
            if sid in result:
                continue
            skill = parse_skill_file(f, sid)
            if skill:
                result[sid] = skill
    return result


class SkillLoader:
    @staticmethod
    def from_configs(configs: dict[str, SkillConfig]) -> SkillRegistry:
        return SkillRegistry().register_many(
            [
                Skill(
                    id=cfg.id,
                    name=cfg.name,
                    description=cfg.description,
                    prompt=cfg.prompt,
                    tools=cfg.tools,
                )
                for cfg in configs.values()
            ]
        )

    @staticmethod
    def build(configs: dict[str, SkillConfig], extra_dirs=()) -> SkillRegistry:
        """合并 toml 技能 + 各文件技能目录（extra_dirs 按顺序，后扫目录覆盖同名 = 更高优先级）。"""
        merged = {s.id: s for s in SkillLoader.from_configs(configs).list()}
        for d in extra_dirs:
            merged.update(scan_skill_dir(d))
        return SkillRegistry().register_many(list(merged.values()))

    @staticmethod
    def compose_prompt(registry: SkillRegistry, enabled: list[str]) -> str:
        """把 agent 启用的技能索引拼进 system prompt：只列 id + description，全文按需经 skill 工具获取。"""
        lines: list[str] = []
        for skill_id in enabled:
            skill = registry.get(skill_id)
            if not skill:
                continue
            desc = skill.description or _first_line(skill.prompt)
            lines.append(f"- {skill_id}: {desc}")
        if not lines:
            return ""
        return (
            "\n\n[可用技能]\n"
            + "\n".join(lines)
            + "\n需要某个技能的详细指令时，调用 skill 工具并传入技能名（如 planning）获取全文。"
        )
