"""内建工具：apply_patch — 应用结构化补丁批量编辑多个文件。

支持一次调用内的三种操作：add file / update file（可重命名）/ delete file。
Update 块使用 unified diff（@@ 行 + -/+ 标记）。
参考 nano_claude.tools.apply_patch，适配 Mira 的 Tool.run / ToolContext.resolve（相对路径以 workspace 为根）。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mira.core.tools.base import Tool, ToolContext, ToolResult, truncate_output


@dataclass
class Hunk:
    type: str  # add | update | delete
    path: str
    contents: str = ""  # add：新文件内容；update：读出的旧内容
    chunks: str = ""  # update：diff 块
    move_path: str = ""  # update：可选重命名目标


def _parse_patch(patch_text: str) -> list[Hunk]:
    hunks: list[Hunk] = []
    lines = patch_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("*** Add File:"):
            path = line[len("*** Add File:") :].strip()
            contents_lines: list[str] = []
            i += 1
            while i < len(lines) and lines[i].startswith("+"):
                contents_lines.append(lines[i][1:])
                i += 1
            hunks.append(Hunk(type="add", path=path, contents="\n".join(contents_lines)))

        elif line.startswith("*** Update File:"):
            path = line[len("*** Update File:") :].strip()
            move_path = ""
            i += 1
            if i < len(lines) and lines[i].startswith("*** Move to:"):
                move_path = lines[i][len("*** Move to:") :].strip()
                i += 1
            chunk_lines: list[str] = []
            while i < len(lines) and not lines[i].startswith("*** "):
                chunk_lines.append(lines[i])
                i += 1
            hunks.append(
                Hunk(type="update", path=path, chunks="\n".join(chunk_lines), move_path=move_path)
            )

        elif line.startswith("*** Delete File:"):
            path = line[len("*** Delete File:") :].strip()
            hunks.append(Hunk(type="delete", path=path))
            i += 1
        else:
            i += 1
    return hunks


def _apply_single_hunk(old_lines: list[str], hunk_lines: list[str]) -> list[str]:
    """对旧内容应用一个 hunk 的 context / remove(-) / add(+) 行，返回新行列表。"""
    result = list(old_lines)
    remove_indices: set[int] = set()
    add_lines: list[str] = []

    # 收集 context 前缀，用于定位 hunk 在文件中的位置
    context_before: list[str] = []
    for line in hunk_lines:
        if line.startswith(" "):
            context_before.append(line[1:])
        elif line.startswith("-") or line.startswith("+"):
            break

    if context_before:
        context_str = "\n".join(context_before)
        full_text = "\n".join(result)
        pos = full_text.find(context_str)
        if pos == -1:
            return result  # 找不到上下文，跳过
        ctx_start = full_text[:pos].count("\n")
        ci = ctx_start
        for line in hunk_lines:
            if line.startswith(" "):
                ci += 1
            elif line.startswith("-"):
                if ci < len(result):
                    remove_indices.add(ci)
                ci += 1
            elif line.startswith("+"):
                add_lines.append(line[1:])
        for r in sorted(remove_indices, reverse=True):
            result.pop(r)
        insert_pos = min(remove_indices) if remove_indices else ctx_start
        for k, a in enumerate(add_lines):
            result.insert(insert_pos + k, a)
        return result

    # 无上下文：以第一个 - 行为锚点做简单替换 / 纯追加
    for line in hunk_lines:
        if line.startswith("-"):
            target = line[1:]
            for j, ol in enumerate(result):
                if ol == target:
                    remove_indices.add(j)
                    break
            break
    for line in hunk_lines:
        if line.startswith("+"):
            add_lines.append(line[1:])
    if remove_indices and add_lines:
        idx = min(remove_indices)
        for r in sorted(remove_indices, reverse=True):
            result.pop(r)
        for k, a in enumerate(add_lines):
            result.insert(idx + k, a)
    return result


def _apply_unified_diff(old_content: str, diff_chunks: str) -> str:
    """应用 unified diff 块到旧内容，返回新内容。"""
    if not diff_chunks.strip():
        return old_content
    lines = old_content.split("\n")
    new_lines = list(lines)
    hunk_pattern = re.compile(r"^@@\s+-\d+(?:,\d+)?\s+\+\d+(?:,\d+)?\s+@@")
    current: list[str] = []
    in_hunk = False
    for diff_line in diff_chunks.split("\n"):
        if hunk_pattern.match(diff_line):
            if current:
                new_lines = _apply_single_hunk(new_lines, current)
            current = []
            in_hunk = True
            continue
        if in_hunk:
            current.append(diff_line)
    if current:
        new_lines = _apply_single_hunk(new_lines, current)
    return "\n".join(new_lines)


class ApplyPatchTool(Tool):
    name = "apply_patch"
    description = (
        "应用结构化补丁批量编辑多个文件。一次调用支持：add file / update file（可 Move to 重命名）/ "
        "delete file；update 块用 unified diff（@@ 行 + -/+ 标记）。多文件改动或 edit 工具精度不足时优先使用。"
    )
    params_schema = {
        "type": "object",
        "properties": {
            "patchText": {
                "type": "string",
                "description": (
                    "完整补丁文本。格式：\n"
                    "  *** Add File: <path>\n"
                    "  +文件内容行\n"
                    "  *** Update File: <path>\n"
                    "  *** Move to: <new_path>  （可选重命名）\n"
                    "  @@ -start,count +start,count @@\n"
                    "  -旧行\n"
                    "  +新行\n"
                    "   上下文行\n"
                    "  *** Delete File: <path>\n"
                ),
            }
        },
        "required": ["patchText"],
    }

    def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
        patch_text = args.get("patchText", "")
        if not patch_text.strip():
            return ToolResult(ok=False, error="缺少 patchText 参数")
        hunks = _parse_patch(patch_text)
        if not hunks:
            return ToolResult(ok=False, error="补丁中未找到有效操作（Add/Update/Delete File）")

        t0 = time.perf_counter()
        errors: list[str] = []
        summary: list[str] = []

        for hunk in hunks:
            path = ctx.resolve(hunk.path)
            if hunk.type == "add":
                if path.exists() and not path.is_dir():
                    errors.append(f"文件已存在: {hunk.path}")
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(hunk.contents, encoding="utf-8")
                summary.append(f"A {hunk.path}")

            elif hunk.type == "delete":
                if not path.exists():
                    errors.append(f"文件不存在: {hunk.path}")
                    continue
                path.unlink()
                summary.append(f"D {hunk.path}")

            elif hunk.type == "update":
                if not path.exists():
                    errors.append(f"文件不存在: {hunk.path}")
                    continue
                try:
                    old = path.read_text(encoding="utf-8")
                except OSError as exc:
                    errors.append(f"读取失败 {hunk.path}: {exc}")
                    continue
                new = _apply_unified_diff(old, hunk.chunks)
                if new == old and hunk.chunks.strip():
                    errors.append(f"补丁未命中任何行（无改动）: {hunk.path}")
                    continue
                path.write_text(new, encoding="utf-8")
                if hunk.move_path:
                    target = ctx.resolve(hunk.move_path)
                    if target != path:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            path.rename(target)
                            summary.append(f"M {hunk.path} -> {hunk.move_path}")
                            continue
                        except OSError as exc:
                            errors.append(f"重命名失败: {exc}")
                            continue
                summary.append(f"U {hunk.path}")

        output = "\n".join(summary) if summary else "（无操作应用）"
        if errors:
            output += "\n错误：\n" + "\n".join(errors)
        truncated, output = truncate_output(output)
        return ToolResult(
            ok=not errors,
            output=output,
            error=None if not errors else "; ".join(errors[:5]),
            truncated=truncated,
            duration_ms=round((time.perf_counter() - t0) * 1000, 1),
        )
