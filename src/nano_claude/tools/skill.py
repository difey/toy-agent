"""Skill tool — domain-specific knowledge injection via SKILL.md files."""

import os
from dataclasses import dataclass
from pathlib import Path

from nano_claude.tool import Tool, ToolContext, ToolExecResult


# ── YAML frontmatter parser (lightweight, no dependency) ────────────────

def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML-like frontmatter from a markdown file.

    Supports the common subset: string keys/values, lists, and nested dicts.
    Falls back gracefully if frontmatter is missing or malformed.
    """
    if not text.startswith("---"):
        return {}, text

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text

    raw = parts[1].strip()
    body = parts[2].strip()

    frontmatter = {}
    current_key = None
    current_list = None

    for line in raw.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # List item (- value)
        if stripped.startswith("- "):
            val = stripped[2:].strip()
            if current_list is not None:
                current_list.append(val)
            elif current_key is not None:
                current_list = [val]
                frontmatter[current_key] = current_list
            continue

        # Reset list tracking on new key
        if current_list is not None:
            current_list = None

        # Key: value
        if ":" in stripped:
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip()
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            elif val.startswith("'") and val.endswith("'"):
                val = val[1:-1]
            frontmatter[key] = val
            current_key = key

    return frontmatter, body


# ── Skill data model ───────────────────────────────────────────────────

@dataclass
class Skill:
    """A domain-specific skill loaded from a SKILL.md file."""
    name: str
    description: str
    location: str          # Absolute path to the SKILL.md file
    content: str           # Markdown body (after frontmatter)
    dir: str = ""          # Directory containing the SKILL.md file

    def __post_init__(self):
        if not self.dir:
            self.dir = os.path.dirname(self.location)


# ── Skill store ────────────────────────────────────────────────────────

class SkillStore:
    """Discovers, stores and retrieves skills from SKILL.md files."""

    def __init__(self):
        self._skills: dict[str, Skill] = {}

    def discover(self, search_dirs: list[str]) -> None:
        """Scan directories for SKILL.md files and load them."""
        pattern = "**/SKILL.md"
        seen: set[str] = set()
        for search_dir in search_dirs:
            base = Path(search_dir).resolve()
            if not base.is_dir():
                continue
            for match in sorted(base.glob(pattern)):
                resolved = str(match.resolve())
                if resolved not in seen:
                    seen.add(resolved)
                    self._load(match)

    def _load(self, path: Path) -> None:
        """Load a single SKILL.md file."""
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return

        frontmatter, body = _parse_frontmatter(text)
        name = frontmatter.get("name", path.parent.name)
        description = frontmatter.get("description", "")
        content = body or text

        self._skills[name] = Skill(
            name=name,
            description=description,
            location=str(path.resolve()),
            content=content,
        )

    def get(self, name: str) -> Skill | None:
        """Get a skill by name."""
        return self._skills.get(name)

    def list_all(self) -> "list[Skill]":
        """Return all discovered skills, sorted by name."""
        return sorted(self._skills.values(), key=lambda s: s.name)

    def list_files(self, skill_name: str, limit: int = 10) -> list[str]:
        """List up to `limit` files in the skill's directory."""
        skill = self._skills.get(skill_name)
        if not skill or not skill.dir:
            return []
        base = Path(skill.dir)
        if not base.is_dir():
            return []
        files = []
        for f in sorted(base.iterdir()):
            if f.is_file() and f.name != "SKILL.md":
                files.append(str(f))
                if len(files) >= limit:
                    break
        return files

    @property
    def count(self) -> int:
        return len(self._skills)


def build_skills_section(skills: list[Skill]) -> str:
    """Build the skills section for injection into the system prompt."""
    if not skills:
        return ""
    lines = [
        "\n## Available Skills",
        "You have the following domain-specific skills available. "
        "Use the `skill` tool to load a skill's instructions when working in that domain.",
        "",
    ]
    for s in skills:
        desc = f" — {s.description}" if s.description else ""
        lines.append(f"- `{s.name}`{desc}")
    lines.append("")
    return "\n".join(lines)


# ── Skill tool ──────────────────────────────────────────────────────────

class SkillTool(Tool):
    @property
    def name(self) -> str:
        return "skill"

    @property
    def description(self) -> str:
        return (
            "Load a domain-specific skill into the conversation. "
            "Skills provide specialized instructions and context for working "
            "in particular domains or frameworks. "
            "Use this when you need domain knowledge for the current task."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the skill to load (see Available Skills in system prompt for the list)",
                },
            },
            "required": ["name"],
        }

    async def execute(self, args: dict, ctx: ToolContext) -> ToolExecResult:
        skill_name = args["name"]

        skill_store: SkillStore | None = getattr(ctx, "skill_store", None)
        if skill_store is None:
            return ToolExecResult(
                output="Error: No skill store available. Skills have not been configured for this project.",
                title="skill [error]",
            )

        skill = skill_store.get(skill_name)
        if not skill:
            available = skill_store.list_all()
            if available:
                names = ", ".join(f"'{s.name}'" for s in available)
                return ToolExecResult(
                    output=f"Skill '{skill_name}' not found. Available skills: {names}",
                    title="skill [error]",
                )
            else:
                return ToolExecResult(
                    output="No skills are available. Create SKILL.md files in your project to define skills.",
                    title="skill [error]",
                )

        # List files in the skill's directory (up to 10)
        files = skill_store.list_files(skill_name, limit=10)

        file_list = ""
        if files:
            file_list = "\n\n<skill_files>\n" + "\n".join(
                f"<file>{f}</file>" for f in files
            ) + "\n</skill_files>"

        output = (
            f"<skill_content name=\"{skill.name}\">\n"
            f"{skill.content}"
            f"\n\nBase directory: {skill.dir}"
            f"{file_list}"
            f"\n</skill_content>"
        )

        return ToolExecResult(
            title=f"skill [{skill.name}]",
            output=output,
            metadata={"skill_name": skill.name, "files": len(files)},
        )
