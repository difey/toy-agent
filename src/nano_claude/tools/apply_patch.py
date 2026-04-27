import os
import re
from dataclasses import dataclass, field

from nano_claude.tool import Tool, ToolContext, ToolExecResult


@dataclass
class Hunk:
    type: str          # "add" | "update" | "delete"
    path: str          # file path
    contents: str      # content for "add"
    chunks: str = ""   # diff chunks for "update"
    move_path: str = ""  # optional rename target for "update"


def _resolve_patch_path(path: str, cwd: str) -> str:
    if not os.path.isabs(path):
        path = os.path.join(cwd, path)
    return os.path.realpath(path)


def _parse_patch(patch_text: str) -> list[Hunk]:
    """Parse structured patch text into hunks."""
    hunks = []
    lines = patch_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith("*** Add File:"):
            path = line[len("*** Add File:"):].strip()
            contents_lines = []
            i += 1
            while i < len(lines) and lines[i].startswith("+"):
                contents_lines.append(lines[i][1:])  # strip leading '+'
                i += 1
            hunks.append(Hunk(
                type="add",
                path=path,
                contents="\n".join(contents_lines),
            ))

        elif line.startswith("*** Update File:"):
            path = line[len("*** Update File:"):].strip()
            move_path = ""
            i += 1
            if i < len(lines) and lines[i].startswith("*** Move to:"):
                move_path = lines[i][len("*** Move to:"):].strip()
                i += 1
            chunk_lines = []
            while i < len(lines) and not lines[i].startswith("*** "):
                chunk_lines.append(lines[i])
                i += 1
            hunks.append(Hunk(
                type="update",
                path=path,
                contents="",
                chunks="\n".join(chunk_lines),
                move_path=move_path,
            ))

        elif line.startswith("*** Delete File:"):
            path = line[len("*** Delete File:"):].strip()
            hunks.append(Hunk(type="delete", path=path, contents="", chunks=""))
            i += 1

        else:
            i += 1

    return hunks


def _apply_unified_diff(old_content: str, diff_chunks: str) -> str:
    """Apply unified diff chunks to old content and return new content."""
    if not diff_chunks.strip():
        return old_content

    lines = old_content.split("\n")
    new_lines = list(lines)

    # Parse each hunk: @@ -start,count +start,count @@
    hunk_pattern = re.compile(r"^@@\s+-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@")
    current_hunk_lines = []
    in_hunk = False
    offset = 0

    for diff_line in diff_chunks.split("\n"):
        m = hunk_pattern.match(diff_line)
        if m:
            # Apply previous hunk
            if current_hunk_lines:
                new_lines = _apply_single_hunk(new_lines, current_hunk_lines, offset)
                offset = _recalc_offset(new_lines, offset)

            current_hunk_lines = []
            in_hunk = True
            continue

        if in_hunk:
            current_hunk_lines.append(diff_line)

    if current_hunk_lines:
        new_lines = _apply_single_hunk(new_lines, current_hunk_lines, offset)

    return "\n".join(new_lines)


def _apply_single_hunk(old_lines: list[str], hunk_lines: list[str], offset: int) -> list[str]:
    """Apply a single hunk's context/remove/add lines."""
    result = list(old_lines)
    remove_indices = set()
    add_lines = []
    remove_count = 0
    add_count = 0

    # First pass: find the hunk position by searching for context lines
    context_before = []
    for line in hunk_lines:
        if line.startswith(" "):
            context_before.append(line[1:])
        elif line.startswith("-"):
            break
        else:
            break

    if not context_before:
        # No context, try to find a unique anchor
        for i, line in enumerate(hunk_lines):
            if line.startswith("-"):
                target = line[1:]
                for j, ol in enumerate(result):
                    if ol == target:
                        remove_indices.add(j)
                        remove_count += 1
                        break
                break
        # Apply additions after
        for line in hunk_lines:
            if line.startswith("+"):
                add_lines.append(line[1:])
                add_count += 1
        # Simple replace
        if remove_indices and add_lines:
            idx = min(remove_indices)
            for r in sorted(remove_indices, reverse=True):
                result.pop(r)
            for k, a in enumerate(add_lines):
                result.insert(idx + k, a)
        elif add_lines and not remove_indices:
            # Pure addition - insert after context
            pass
        return result

    # Find context in old_lines
    context_str = "\n".join(context_before)
    full_text = "\n".join(result)
    pos = full_text.find(context_str)
    if pos == -1:
        return result  # Can't find context, skip

    ctx_start_line = full_text[:pos].count("\n")

    # Now parse the hunk relative to ctx_start_line
    ci = ctx_start_line
    for line in hunk_lines:
        if line.startswith(" "):
            ci += 1  # context line, skip
        elif line.startswith("-"):
            remove_indices.add(ci)
            remove_count += 1
            ci += 1
        elif line.startswith("+"):
            add_lines.append(line[1:])
            add_count += 1

    # Apply changes
    for r in sorted(remove_indices, reverse=True):
        if r < len(result):
            result.pop(r)

    insert_pos = min(remove_indices) if remove_indices else ctx_start_line
    for k, a in enumerate(add_lines):
        result.insert(insert_pos + k, a)

    return result


def _recalc_offset(lines: list[str], current_offset: int) -> int:
    """Recalculate line offset after changes (unused but kept for structure)."""
    return current_offset


class ApplyPatchTool(Tool):
    @property
    def name(self) -> str:
        return "apply_patch"

    @property
    def description(self) -> str:
        return (
            "Apply a structured patch to batch-edit multiple files. "
            "Supports three operations in one call: add file, update file (with optional rename), "
            "and delete file. "
            "Update blocks use unified diff format (@@ lines + -/+ markers). "
            "Prefer this tool when making multi-file changes or when edit tool struggles with precision. "
            "For single simple edits, use the edit tool instead."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "patchText": {
                    "type": "string",
                    "description": (
                        "The complete patch text. Format:\n"
                        "  *** Add File: <path>\n"
                        "  +file content line\n"
                        "  +another line\n"
                        "  *** Update File: <path>\n"
                        "  *** Move to: <new_path>  (optional rename)\n"
                        "  @@ -start,count +start,count @@\n"
                        "  -old line\n"
                        "  +new line\n"
                        "   context line\n"
                        "  *** Delete File: <path>\n"
                    ),
                },
            },
            "required": ["patchText"],
        }

    async def execute(self, args: dict, ctx: ToolContext) -> ToolExecResult:
        patch_text = args["patchText"]
        hunks = _parse_patch(patch_text)

        if not hunks:
            return ToolExecResult(
                output="Error: No valid patch operations found in patch text.",
                title="apply_patch [error]",
            )

        summary = []
        errors = []

        for hunk in hunks:
            resolved_path = _resolve_patch_path(hunk.path, ctx.cwd)

            if hunk.type == "add":
                parent = os.path.dirname(resolved_path)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                try:
                    with open(resolved_path, "w", encoding="utf-8") as f:
                        f.write(hunk.contents)
                    summary.append(f"A {hunk.path}")
                except OSError as e:
                    errors.append(f"Failed to create {hunk.path}: {e}")

            elif hunk.type == "delete":
                if not os.path.exists(resolved_path):
                    errors.append(f"File not found: {hunk.path}")
                    continue
                try:
                    os.remove(resolved_path)
                    summary.append(f"D {hunk.path}")
                except OSError as e:
                    errors.append(f"Failed to delete {hunk.path}: {e}")

            elif hunk.type == "update":
                if not os.path.exists(resolved_path):
                    errors.append(f"File not found: {hunk.path}")
                    continue
                try:
                    with open(resolved_path, "r", encoding="utf-8") as f:
                        old_content = f.read()

                    new_content = _apply_unified_diff(old_content, hunk.chunks)

                    target_path = resolved_path
                    if hunk.move_path:
                        target_path = _resolve_patch_path(hunk.move_path, ctx.cwd)
                        parent = os.path.dirname(target_path)
                        if parent:
                            os.makedirs(parent, exist_ok=True)

                    with open(target_path, "w", encoding="utf-8") as f:
                        f.write(new_content)

                    if hunk.move_path and hunk.move_path != hunk.path:
                        if os.path.exists(resolved_path) and resolved_path != target_path:
                            try:
                                os.remove(resolved_path)
                            except OSError:
                                pass
                        summary.append(f"M {hunk.path} → {hunk.move_path}")
                    else:
                        summary.append(f"M {hunk.path}")

                except OSError as e:
                    errors.append(f"Failed to update {hunk.path}: {e}")

        output_parts = []
        if summary:
            output_parts.append("Updated:\n" + "\n".join(summary))
        if errors:
            output_parts.append("Errors:\n" + "\n".join(errors))

        result_output = "\n\n".join(output_parts) if output_parts else "(no changes made)"

        return ToolExecResult(
            title=f"apply_patch [{len(summary)} files]",
            output=result_output,
        )
