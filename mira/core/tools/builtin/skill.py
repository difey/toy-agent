"""skill：按需获取某个技能（SKILL.md）的完整指令，作为 tool result 返回给 LLM。

设计要点（按需加载，省 system prompt token）：
- system prompt 只列启用技能的 description（[可用技能] 索引），不拼全文；
- LLM 需要某技能详细指令时调用本工具（参数 name=技能名），工具把该技能全文作为 tool result 返回；
- 全文来自当前 runtime 的技能注册表（configs/skills + ~/.agents + ~/.mira-code + workspace/.skills 合并），
  经 runtime 注入的 `skill_lookup` 钩子获取（与 attach_image 的 meta 钩子同模式）。
"""

from __future__ import annotations

from typing import Any

from mira.core.tools.base import Tool, ToolContext, ToolResult


class SkillTool(Tool):
    name = "skill"
    description = (
        "获取某个技能（skill）的完整指令文本。参数 name 为技能名（见 system prompt 的 [可用技能] 列表）。"
        "返回该技能的详细执行指令，请按其执行。"
    )
    params_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "技能名，如 planning / code-exploration"},
        },
        "required": ["name"],
    }

    def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
        name = str(args.get("name") or "").strip()
        if not name:
            return ToolResult(ok=False, error="skill 需要 name 参数（技能名）")
        lookup = (ctx.meta or {}).get("skill_lookup")
        if lookup is None:
            return ToolResult(ok=False, error="skill 需在运行时会话中执行（缺少 skill_lookup 钩子）")
        try:
            skill = lookup(name)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"获取技能失败: {exc}")
        if skill is None:
            return ToolResult(
                ok=False,
                error=f"未找到技能: {name}（可用技能见 system prompt 的 [可用技能] 列表）",
            )
        head = f"# 技能 {skill.id}"
        if skill.description:
            head += f"\n> {skill.description}"
        body = (skill.prompt or "").strip()
        return ToolResult(ok=True, output=(head + "\n\n" + body).strip())