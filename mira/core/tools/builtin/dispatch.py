"""内建工具：dispatch_task — 主 agent 把子任务分派给子 agent（P3 编排）。

- 经运行时注入的 dispatcher（ToolContext.meta["dispatcher"]）执行；
- 可选目标动态来自 agents registry（配置即注册）：新增/修改子 agent 配置后主 agent 自动感知；
- 返回汇报摘要 + 完整报告路径（决策 #7：只回填摘要，细节用 file_read 读报告）。
"""

from __future__ import annotations

from typing import Any

from mira.api.protocol import TaskSpec
from mira.core.tools.base import Tool, ToolContext, ToolResult


class DispatchTaskTool(Tool):
    name = "dispatch_task"

    def __init__(self, available: list[dict[str, str]] | None = None) -> None:
        """available：当前可自动分派的子 agent 元信息 [{id, name, description}]（动态来自 registry）。"""
        self._available = [dict(a) for a in (available or [])]
        if self._available:
            targets = " / ".join(
                f"{a['id']}（{a.get('name') or a.get('description') or ''}）"[:60]
                for a in self._available
            )
            target_desc = "；".join(
                f"{a['id']}（{a.get('description') or a.get('name') or ''}）"[:80]
                for a in self._available
            )
        else:
            targets = "（无可用子代理）"
            target_desc = "（当前无可分派的子 agent）"
        self.description = (
            f"把子任务分派给子 agent（{targets}）执行，返回汇报摘要与完整报告路径。"
            "子 agent 上下文与主对话完全隔离；需要完整细节时用 file_read 读取报告路径。"
        )
        self.params_schema = {
            "type": "object",
            "properties": {
                "target_agent": {
                    "type": "string",
                    "description": "可选目标：" + target_desc,
                },
                "goal": {"type": "string", "description": "子任务目标（一句话）"},
                "instructions": {"type": "string", "description": "附加要求（可选）"},
                "context": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "参考文件路径 / 文档（可选）",
                },
                "images": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "图片绝对路径列表（视觉 agent 用视觉模型查看；可选）",
                },
            },
            "required": ["target_agent", "goal"],
        }

    def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
        dispatcher = (ctx.meta or {}).get("dispatcher")
        if dispatcher is None:
            return ToolResult(
                ok=False, error="dispatch_task 需要在运行时会话中执行（缺少 dispatcher）"
            )
        target = str(args.get("target_agent", "")).strip()
        goal = str(args.get("goal", "")).strip()
        if not target or not goal:
            return ToolResult(ok=False, error="target_agent 与 goal 为必填参数")
        if self._available and target not in {a["id"] for a in self._available}:
            ids = "、".join(a["id"] for a in self._available)
            return ToolResult(ok=False, error=f"未知子 agent: {target!r}（可用: {ids}）")

        spec = TaskSpec(
            target_agent=target,
            goal=goal,
            instructions=str(args.get("instructions", "") or ""),
            context=list(args.get("context") or []),
            images=list(args.get("images") or []),
        )
        parent_span = str((ctx.meta or {}).get("span_id") or "")
        try:
            meta = ctx.meta or {}
            provider = meta.get("provider")
            model = meta.get("model")
            # 模型串 {provider}/{model}：把父 runtime 本轮 provider+model 组合传给子任务（决策 #25/#26）
            inherit = f"{provider}/{model}" if provider and model else (model or None)
            report = dispatcher.dispatch(
                spec,
                ctx.session_id,
                parent_span,
                model=inherit,
                effort=meta.get("effort"),
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"任务分派失败: {exc}")

        return ToolResult(
            ok=report.status.value == "succeeded",
            output=(
                f"子任务 {report.task_id}（{report.agent_id}）已完成，状态：{report.status.value}\n"
                f"摘要：{report.summary or '（无）'}\n"
                f"完整报告：{report.report_path}"
            ),
        )
