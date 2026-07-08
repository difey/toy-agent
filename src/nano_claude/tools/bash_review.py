import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from nano_claude.infra.llm import LLMClient
from nano_claude.core.message import UserMessage


@dataclass
class BashReviewResult:
    """Result of a sub-agent bash command review."""
    verdict: str  # "safe", "suspicious", or "dangerous"
    summary: str
    risk_description: str
    affected_paths: list[str] = field(default_factory=list)
    recommendation: str = ""


# Commands that are trivially safe and don't need review
_HARMLESS_COMMANDS = frozenset({
    "ls", "echo", "pwd", "cd", "clear", "which", "whoami", "id",
    "date", "time", "cal", "uptime", "uname", "env", "printenv",
    "type", "alias", "dirs", "history", "popd", "pushd",
})


def is_harmless_command(command: str) -> bool:
    """Check if a command is trivially safe (no side effects).

    Returns True for commands like ``ls``, ``echo``, ``pwd``, etc.
    These commands are so benign that review would be a waste of time and tokens.
    """
    first = command.strip().split(maxsplit=1)[0] if command.strip() else ""
    return first in _HARMLESS_COMMANDS


def detect_external_dir_operation(command: str, cwd: str, workdir: str) -> bool:
    """Check if the command operates on directories outside the project cwd.

    Returns True if any of these conditions hold:
    - The explicit *workdir* parameter differs from *cwd*
    - The command contains ``..`` or absolute paths outside *cwd*
    """
    # 1. Explicit workdir mismatch
    try:
        if os.path.realpath(workdir) != os.path.realpath(cwd):
            return True
    except OSError:
        pass

    # 2. Token-level path analysis
    try:
        tokens = command.split()
    except Exception:
        tokens = []

    for token in tokens:
        # Skip options and non-path tokens
        if token.startswith("-") or "=" in token:
            continue
        # Check for parent-directory traversal
        if token.startswith("..") or "/.." in token:
            return True
        # Check absolute paths that point outside cwd
        if os.path.isabs(token):
            try:
                resolved = os.path.realpath(token)
                real_cwd = os.path.realpath(cwd)
                if not resolved.startswith(real_cwd + "/") and resolved != real_cwd:
                    return True
            except OSError:
                pass

    return False


def gather_project_context(cwd: str, max_entries: int = 50) -> str:
    """Collect a lightweight summary of the project structure for the reviewer.

    Returns a multi-line string with:
    - Top-level directory entries
    - Detected project type (Python, Node.js, Rust, etc.)
    """
    lines = []
    try:
        entries = sorted(
            os.listdir(cwd),
            key=lambda x: (not os.path.isdir(os.path.join(cwd, x)), x.lower()),
        )
        lines.append(f"Top-level entries ({len(entries)} total):")
        for i, entry in enumerate(entries[:max_entries]):
            full = os.path.join(cwd, entry)
            suffix = "/" if os.path.isdir(full) else ""
            lines.append(f"  {entry}{suffix}")
        if len(entries) > max_entries:
            lines.append(f"  ... and {len(entries) - max_entries} more")
    except PermissionError:
        lines.append("(cannot list directory – permission denied)")
    except OSError as e:
        lines.append(f"(cannot list directory – {e})")

    # Detect project type from well-known manifest files
    project_type_map = {
        "pyproject.toml": "Python (PEP 621 / Poetry)",
        "setup.py": "Python",
        "setup.cfg": "Python",
        "requirements.txt": "Python",
        "Pipfile": "Python (Pipenv)",
        "package.json": "Node.js / JavaScript",
        "yarn.lock": "Node.js (Yarn)",
        "Cargo.toml": "Rust",
        "go.mod": "Go",
        "Gemfile": "Ruby",
        "Makefile": "Make-based build",
        "CMakeLists.txt": "CMake",
        "composer.json": "PHP",
        "build.gradle": "Gradle",
        "pom.xml": "Maven",
        "mix.exs": "Elixir",
        "Project.toml": "Julia",
    }
    for filename, project_type in project_type_map.items():
        if os.path.exists(os.path.join(cwd, filename)):
            lines.append(f"\nDetected project type: {project_type}")
            break

    return "\n".join(lines)


def _load_review_prompt() -> str:
    """Load the reviewer system prompt from the adjacent ``.txt`` file.

    Falls back to a built-in default if the file is missing.
    """
    prompt_path = os.path.join(os.path.dirname(__file__), "bash_review.txt")
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except (FileNotFoundError, OSError):
        return _DEFAULT_REVIEW_PROMPT


async def run_bash_review(
    command: str,
    workdir: str,
    cwd: str,
    description: str,
    llm_client: LLMClient,
) -> BashReviewResult:
    """Run a sub-agent semantic review of a bash command for safety.

    This is a single-turn LLM call. The LLM receives the command,
    project context, and a structured prompt, then returns a JSON
    verdict.
    """
    project_structure = gather_project_context(cwd)
    prompt_template = _load_review_prompt()

    review_prompt = prompt_template.format(
        command=command,
        cwd=cwd,
        workdir=workdir,
        description=description or "(none)",
        project_structure=project_structure,
    )

    try:
        response = await llm_client.chat(
            messages=[UserMessage(content=review_prompt)],
            tools=[],
        )
        content = response.content or ""

        result = _parse_review_json(content)
        if result is not None:
            return result

        # Failed to parse JSON — treat as suspicious
        return BashReviewResult(
            verdict="suspicious",
            summary="Review returned unparseable output",
            risk_description=(
                f"The review agent returned content that could not be parsed "
                f"as a valid JSON verdict. Raw output (first 300 chars): "
                f"{content[:300]}"
            ),
            affected_paths=[],
            recommendation="Review the command manually before proceeding.",
        )

    except Exception as exc:
        return BashReviewResult(
            verdict="suspicious",
            summary=f"Review failed: {exc}",
            risk_description="The review agent encountered an error during analysis.",
            affected_paths=[],
            recommendation="Review the command manually before proceeding.",
        )


def _parse_review_json(content: str) -> Optional[BashReviewResult]:
    """Extract a ``BashReviewResult`` from the LLM's text output.

    Handles these formats:
    - Raw JSON object (preferred)
    - JSON inside markdown code fences (```json ... ```)
    """
    # Strategy 1: markdown code fence
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
    if match:
        json_str = match.group(1)
    else:
        # Strategy 2: bare JSON object
        match = re.search(r'\{[\s\S]*\}', content)
        if match:
            json_str = match.group(0)
        else:
            return None

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return None

    verdict = data.get("verdict", "suspicious")
    if verdict not in ("safe", "suspicious", "dangerous"):
        verdict = "suspicious"

    return BashReviewResult(
        verdict=verdict,
        summary=data.get("summary", ""),
        risk_description=data.get("risk_description", ""),
        affected_paths=data.get("affected_paths", []),
        recommendation=data.get("recommendation", ""),
    )


# ---------------------------------------------------------------------------
# Built-in fallback prompt (used when ``bash_review.txt`` is missing)
# ---------------------------------------------------------------------------
_DEFAULT_REVIEW_PROMPT = """You are a Bash command security reviewer. Analyze whether the given command is safe.

## Context
- Command: {command}
- Working directory: {cwd}
- Target directory: {workdir}
- Description: {description}
- Project structure:
{project_structure}

## Output (JSON only, no extra text)
{{
  "verdict": "safe" | "suspicious" | "dangerous",
  "summary": "what this command does in one sentence",
  "risk_description": "specific risks, if any; empty string if safe",
  "affected_paths": ["paths that would be affected"],
  "recommendation": "allow, deny, or manual review"
}}
"""
