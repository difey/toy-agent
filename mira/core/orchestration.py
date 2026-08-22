"""P3 编排：TaskDispatcher 把子任务分派给子 agent（investigator / proto-tester 等）。

- 子 agent 上下文完全隔离（独立 runtime / 空 history，不污染主 agent 上下文）；
- 产出独立 span 树：`main → task.dispatch → agent.spawn → agent.loop.* → agent.join`；
- 完整报告落盘（决策 #7 / #9），只回填摘要给主 agent；
- 子 agent 的 MCP 工具同样接入（按 agent 的 mcp.enabled 集合）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mira.api.approval import ApprovalGate
from mira.api.protocol import AgentReport, ReportStatus, TaskSpec
from mira.core.agents.registry import AgentRegistry
from mira.core.config.store import ConfigStore
from mira.core.mcp.manager import McpManager
from mira.core.providers.base import ChatMessage, ChatRole
from mira.core.providers.router import ProviderRouter
from mira.core.runtime import AgentRuntime
from mira.core.skills.registry import SkillRegistry
from mira.core.tools.permission import PermissionChecker
from mira.core.tools.registry import ToolRegistry
from mira.telemetry.events import EventType
from mira.telemetry.reports import save_report
from mira.telemetry.tracer import BaseTracer
from mira.util import short_hash

SUMMARY_LIMIT = 600


class TaskDispatcher:
    """子任务编排：isolated 子 agent 运行 + 结构化汇报 + 报告落盘。"""

    def __init__(
        self,
        *,
        store: ConfigStore,
        agents: AgentRegistry,
        router: ProviderRouter,
        skills: SkillRegistry | None,
        tracer: BaseTracer,
        workspace: str | Path,
        approvals: ApprovalGate | None = None,
        mcp_manager: McpManager | None = None,
        auto_approver: Any | None = None,  # 自动审批决策器（透传给子 agent runtime）
    ) -> None:
        self.store = store
        self.agents = agents
        self.router = router
        self.skills = skills
        self.tracer = tracer
        self.workspace = Path(workspace)
        self.approvals = approvals
        self.mcp = mcp_manager
        self.auto_approver = auto_approver

    # ── 主入口 ───────────────────────────────────────────────

    def dispatch(
        self,
        spec: TaskSpec,
        session_id: str,
        parent_span_id: str,
        *,
        model: str | None = None,  # 父 runtime 本轮 model（继承源，决策 #25）
        effort: str | None = None,  # 父 runtime 本轮 effort（继承源，决策 #25）
    ) -> AgentReport:
        """执行一次子任务分派，返回结构化汇报（摘要已截断，完整报告已落盘）。"""
        if not self.agents.has(spec.target_agent):
            raise ValueError(
                f"未注册的子 agent: {spec.target_agent!r}（可用: {self.agents.ids()}）"
            )

        dispatch_span = f"sp_dispatch_{short_hash(spec.task_id, 6)}"
        self.tracer.emit(
            EventType.TASK_DISPATCH,
            {
                "task_id": spec.task_id,
                "target_agent": spec.target_agent,
                "goal": spec.goal,
            },
            session_id=session_id,
            span_id=dispatch_span,
            parent_span_id=parent_span_id,
        )

        spawn_span = f"sp_agent_{spec.target_agent}_{short_hash(spec.task_id, 6)}"
        self.tracer.emit(
            EventType.AGENT_SPAWN,
            {"agent_id": spec.target_agent, "task_id": spec.task_id},
            session_id=session_id,
            span_id=spawn_span,
            parent_span_id=dispatch_span,
        )

        sub = self._build_sub_runtime(spec.target_agent)
        # 决策 #25：子 agent 的 model/effort 可选；未配置则继承父 runtime 本轮值（经 model/effort 参数传入）
        agent = self.agents.get(spec.target_agent)
        sub_model = agent.model or model or ""
        sub_effort = agent.effort if agent.effort is not None else effort
        report = AgentReport(task_id=spec.task_id, agent_id=spec.target_agent)
        reply = ""
        try:
            self.tracer.emit(
                EventType.TASK_START,
                {"task_id": spec.task_id, "target_agent": spec.target_agent},
                session_id=session_id,
                span_id=spawn_span,
                parent_span_id=dispatch_span,
            )
            prompt = self._compose_task_prompt(spec)
            # 图片以多模态 user 消息注入（视觉 agent 用视觉模型查看）
            extra = None
            if spec.images:
                extra = [
                    ChatMessage(
                        role=ChatRole.USER,
                        content="（用户附加了图片，请用视觉能力查看并回答）",
                        images=list(spec.images),
                    )
                ]
            reply = sub.run(
                prompt,
                session_id,
                parent_span_id=spawn_span,
                model=sub_model,
                effort=sub_effort,
                extra_history=extra,
            )
            report.status = ReportStatus.SUCCEEDED
            report.summary = reply.strip()[:SUMMARY_LIMIT]
        except Exception as exc:  # noqa: BLE001
            report.status = ReportStatus.FAILED
            report.summary = f"子任务失败: {exc}"
            reply = reply or report.summary
            self.tracer.emit(
                EventType.TASK_FAILED,
                {"task_id": spec.task_id, "error": str(exc)},
                session_id=session_id,
                span_id=spawn_span,
                parent_span_id=dispatch_span,
            )

        report.report_path = str(save_report(self.workspace, session_id, report, body=reply))

        self.tracer.emit(
            EventType.AGENT_JOIN,
            {
                "task_id": spec.task_id,
                "agent_id": spec.target_agent,
                "status": report.status.value,
            },
            session_id=session_id,
            span_id=spawn_span,
            parent_span_id=dispatch_span,
        )
        self.tracer.emit(
            EventType.TASK_COMPLETE,
            {
                "task_id": spec.task_id,
                "status": report.status.value,
                "report_path": report.report_path,
            },
            session_id=session_id,
            span_id=dispatch_span,
            parent_span_id=parent_span_id,
        )
        self.tracer.emit(
            EventType.AGENT_REPORT,
            {
                "task_id": spec.task_id,
                "agent_id": spec.target_agent,
                "status": report.status.value,
                "summary": report.summary,
                "report_path": report.report_path,
            },
            session_id=session_id,
            span_id=dispatch_span,
            parent_span_id=parent_span_id,
        )
        return report

    # ── 子 runtime ───────────────────────────────────────────

    def _build_sub_runtime(self, agent_id: str) -> AgentRuntime:
        """构造上下文完全隔离的子 agent runtime（空 history，独立工具注册表）。"""
        agent = self.agents.get(agent_id)
        tools = ToolRegistry.with_builtins()
        mcp_tools = self.mcp.tools_for(agent) if self.mcp else []
        for t in mcp_tools:
            tools.register(t)
        effective = agent.enabled_tools() + [t.name for t in mcp_tools]
        permissions = PermissionChecker(
            agent.config.permission.rules, mode=self.store.runtime().approval.mode
        )
        return AgentRuntime(
            agent=agent,
            router=self.router,
            tools=tools,
            permissions=permissions,
            tracer=self.tracer,
            workspace=self.workspace,
            skills=self.skills,
            token_budget=agent.config.token_budget,
            approvals=self.approvals,
            auto_approver=self.auto_approver,
            tools_override=effective,
        )

    @staticmethod
    def _compose_task_prompt(spec: TaskSpec) -> str:
        parts = [f"任务目标：{spec.goal or ''}".strip()]
        if spec.instructions:
            parts.append(f"要求：{spec.instructions}")
        if spec.context:
            parts.append("参考上下文：\n" + "\n".join(f"- {c}" for c in spec.context))
        if spec.images:
            # 图片路径也写入文本 prompt：多模态注入可能因模型不支持而失效，
            # 子 agent 至少能凭路径自行用 attach_image 查看，而不是靠"反思"猜测
            parts.append(
                "附加图片路径（如需查看请用 attach_image 工具把图片加入上下文）：\n"
                + "\n".join(f"- {p}" for p in spec.images)
            )
        if spec.expected_output:
            parts.append(f"期望输出：{spec.expected_output}")
        return "\n\n".join(p for p in parts if p).strip()
