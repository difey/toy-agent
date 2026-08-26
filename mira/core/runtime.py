"""AgentRuntime 执行循环。

循环：组装上下文 → 调 Provider(stream) → 解析输出 → (需要工具? 执行工具 → 回填结果) → 循环 → 结束。
所有关键动作经注入式 Tracer 产出结构化事件（llm.* / tool.* / agent.*）。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any, Callable

from mira.api.approval import ApprovalDecision, ApprovalGate, ApprovalRequest, ApprovalStatus
from mira.api.questions import QuestionGate
from mira.core.agents.base import BaseAgent
from mira.core.context import build_context
from mira.core.providers.base import ChatMessage, ChatRole
from mira.core.providers.router import ProviderRouter
from mira.core.skills.registry import SkillRegistry
from mira.core.tools.base import ToolContext, ToolResult
from mira.core.tools.permission import PermissionAction, PermissionChecker
from mira.core.tools.registry import ToolRegistry
from mira.telemetry.events import EventType
from mira.telemetry.tracer import BaseTracer
from mira.util import new_session_id, short_hash, split_spec, utcnow_iso


class AgentRuntime:
    """一次 agent 会话的执行循环（跨多轮用户消息保持 history）。"""

    def __init__(
        self,
        *,
        agent: BaseAgent,
        router: ProviderRouter,
        tools: ToolRegistry,
        permissions: PermissionChecker,
        tracer: BaseTracer,
        workspace: str | Path,
        skills: SkillRegistry | None = None,
        max_steps: int = 12,
        token_budget: int | None = None,
        approvals: ApprovalGate | None = None,
        questions: QuestionGate | None = None,
        auto_approver: Callable[[str, dict, str | None], ApprovalDecision | None] | None = None,
        dispatcher: Any = None,  # P3：TaskDispatcher（dispatch_task 工具回调）
        tools_override: list[str] | None = None,  # P3：工具白名单覆盖（含 MCP 工具）
        stop_event: Event | None = None,  # 停止生成：置位后中断当前回复
    ) -> None:
        self.agent = agent
        self.router = router
        self.tools = tools
        self.permissions = permissions
        self.tracer = tracer
        self.workspace = Path(workspace)
        self.skills = skills
        self.max_steps = max_steps
        self.token_budget = token_budget
        self.approvals = approvals  # P2：ask 命中时的阻塞审批通道（None=自动放行）
        self.questions = questions  # 提问通道：ask_question 工具挂起问题并等待用户作答
        # 自动审批决策器（approval.mode=auto 时由 SessionManager 注入）：
        # (tool, args, path) -> allow/deny；返回 None 表示无法判断 → 回退人工审批
        self.auto_approver = auto_approver
        self.dispatcher = dispatcher  # P3
        self.tools_override = tools_override  # P3
        self._stop_event = stop_event
        self.history: list[ChatMessage] = []
        # attach_image 工具注入的图片路径：在下一轮 _llm_call 发送前转多模态 USER 消息
        self._pending_images: list[str] = []
        self._tokens_in = 0
        self._tokens_out = 0
        self._cost_usd = 0.0

    # ── 主入口 ───────────────────────────────────────────────

    def run(
        self,
        user_text: str,
        session_id: str,
        parent_span_id: str | None = None,
        *,
        model: str | None = None,
        effort: str | None = None,
        extra_history: list[ChatMessage] | None = None,
    ) -> str:
        # model/effort 是每轮请求参数（决策 #25）：override agent 配置，缺省用 agent.model/effort
        eff_model = model or self.agent.model or ""
        eff_effort = effort if effort is not None else self.agent.effort
        # 模型串 {provider}/{model}：provider 由模型推导（决策 #26，不存 provider 状态）
        eff_provider, eff_model = split_spec(eff_model)
        run_span = f"sp_{short_hash(f'{session_id}:{utcnow_iso()}:{user_text[:16]}', 8)}"
        self.tracer.emit(
            EventType.USER_MESSAGE,
            {"content": user_text},
            session_id=session_id,
            span_id=run_span,
            parent_span_id=parent_span_id,
        )
        self.tracer.emit(
            EventType.AGENT_LOOP_START,
            {"agent": self.agent.id, "model": eff_model, "provider": eff_provider},
            session_id=session_id,
            span_id=run_span,
            parent_span_id=parent_span_id,
        )
        # 遥测：首次执行（history 为空）时记录当时生效的 system prompt（含技能注入）
        if not self.history:
            self.tracer.emit(
                EventType.SESSION_SYSTEM_PROMPT,
                {
                    "agent": self.agent.id,
                    "prompt": self.agent.compose_system_prompt(self.skills),
                },
                session_id=session_id,
                span_id=run_span,
                parent_span_id=parent_span_id,
            )
        # extra_history：用户消息的"前导"（如选中的文件路径提示），与 user_text 同属一轮上下文
        for msg in (extra_history or []):
            self.history.append(msg)
        self.history.append(ChatMessage(role=ChatRole.USER, content=user_text))

        reply = ""
        step = 0
        for step in range(1, self.max_steps + 1):
            if self._stop_event is not None and self._stop_event.is_set():
                self.tracer.emit(
                    EventType.ERROR_RAISED,
                    {"message": "已停止生成"},
                    session_id=session_id,
                    span_id=run_span,
                )
                break
            self._check_token_budget(session_id, run_span)
            content, reasoning_content, tool_calls, finish = self._llm_call(
                session_id, run_span, step, provider=eff_provider, model=eff_model, effort=eff_effort, prompt=user_text
            )

            if tool_calls:
                self.history.append(
                    ChatMessage(
                        role=ChatRole.ASSISTANT,
                        content=content,
                        reasoning_content=reasoning_content,
                        tool_calls=tool_calls,
                    )
                )
                self._execute_tools(
                    tool_calls, session_id, run_span, provider=eff_provider, model=eff_model, effort=eff_effort
                )
                continue

            reply = content
            self.history.append(
                ChatMessage(
                    role=ChatRole.ASSISTANT,
                    content=content,
                    reasoning_content=reasoning_content,
                )
            )
            if content:
                self.tracer.emit(
                    EventType.AGENT_MESSAGE,
                    {"content": content, "agent": self.agent.id},
                    session_id=session_id,
                    span_id=run_span,
                )
            break
        else:
            reply = reply or "（已达最大执行步数，任务未完成）"
            self.tracer.emit(
                EventType.ERROR_RAISED,
                {"message": f"超过最大步数 {self.max_steps}"},
                session_id=session_id,
                span_id=run_span,
            )

        self.tracer.emit(
            EventType.AGENT_LOOP_END,
            {
                "agent": self.agent.id,
                "reply": reply,
                "steps": step,
                "usage": {
                    "input_tokens": self._tokens_in,
                    "output_tokens": self._tokens_out,
                    "total_tokens": self._tokens_in + self._tokens_out,
                    "cost_usd": round(self._cost_usd, 6),
                },
            },
            session_id=session_id,
            span_id=run_span,
        )
        return reply

    # ── LLM 调用 ─────────────────────────────────────────────

    def _llm_call(
        self, session_id: str, run_span: str, step: int, *, provider: str, model: str, effort: str | None, prompt: str = ""
    ) -> tuple[str, str, list | None, str | None]:
        messages, tool_specs = build_context(
            self.agent, self.history, self.tools, self.skills, tool_names=self.tools_override
        )
        # attach_image：把工具加入的图片作为多模态 USER 消息追加到 messages 末尾
        # （在 TOOL 结果之后，不插入 assistant(tool_calls) 与 TOOL 之间，保证 tool_call 完整性）
        if self._pending_images:
            for img in self._pending_images:
                messages.append(
                    ChatMessage(
                        role=ChatRole.USER,
                        content="（工具已附加图片，请用视觉能力查看并描述）",
                        images=[img],
                    )
                )
            self._pending_images.clear()
        span = f"sp_llm_{step}"
        self.tracer.emit(
            EventType.LLM_REQUEST,
            {
                "provider": provider,
                "model": model,
                "effort": effort,
                "step": step,
                "tools": [s["function"]["name"] for s in tool_specs],
                "tools_schema": tool_specs,
                "prompt": prompt,
            },
            session_id=session_id,
            span_id=span,
            parent_span_id=run_span,
        )

        buf: list[str] = []
        reasoning_buf: list[str] = []
        usage = None
        tool_calls: list[dict] | None = None
        finish: str | None = None
        for chunk in self.router.stream_chat(
            provider,
            messages,
            model=model,
            temperature=self.agent.config.temperature,
            max_tokens=self.agent.config.max_tokens,
            tools=tool_specs or None,
            effort=effort,
        ):
            if self._stop_event is not None and self._stop_event.is_set():
                finish = "stop"
                break
            if chunk.text:
                buf.append(chunk.text)
                self.tracer.emit(
                    EventType.LLM_STREAM_CHUNK,
                    {"text": chunk.text, "step": step},
                    session_id=session_id,
                    span_id=span,
                    parent_span_id=run_span,
                )
            if chunk.reasoning_content:
                reasoning_buf.append(chunk.reasoning_content)
            if chunk.usage:
                usage = chunk.usage
            if chunk.tool_calls:
                tool_calls = chunk.tool_calls
            if chunk.done:
                finish = chunk.finish_reason or finish

        content = "".join(buf)
        reasoning_content = "".join(reasoning_buf)
        if usage:
            self._tokens_in += usage.input_tokens
            self._tokens_out += usage.output_tokens
            self._cost_usd += usage.cost_usd

        self.tracer.emit(
            EventType.LLM_RESPONSE,
            {
                "content": content,
                "reasoning_content": reasoning_content,
                "finish_reason": finish,
                "step": step,
                "usage": usage.model_dump() if usage else {},
                "tool_calls": tool_calls,
            },
            session_id=session_id,
            span_id=span,
            parent_span_id=run_span,
        )
        return content, reasoning_content, tool_calls, finish

    # ── attach_image 钩子 ────────────────────────────────────

    def _attach_image(self, path: str) -> None:
        """attach_image 工具回调：把图片路径加入待注入队列，下一轮请求前作为多模态消息发送。"""
        self._pending_images.append(path)

    def _lookup_skill(self, name: str):
        """skill 工具回调：从当前 runtime 的技能注册表取技能全文（含 workspace/.skills 叠加）。"""
        return self.skills.get(name) if self.skills else None

    # ── 工具执行 ─────────────────────────────────────────────

    def _execute_tools(
        self,
        tool_calls: list[dict],
        session_id: str,
        run_span: str,
        *,
        provider: str,
        model: str,
        effort: str | None,
    ) -> None:
        # 提问进度：统计同一批 tool_calls 中 ask_question 的序号/总数（前端展示 2/4 等）
        ask_total = sum(
            1
            for c in tool_calls
            if ((c.get("function") or {}).get("name") or "") == "ask_question"
        )
        ask_seen = 0
        for idx, call in enumerate(tool_calls, 1):
            function = call.get("function") or {}
            name = function.get("name", "")
            args, parse_err = self._parse_args(function.get("arguments"))
            path = args.get("path") or args.get("cwd")
            action = self.permissions.check(name, str(path) if path else None)
            # 当前是否为 ask_question 及其在本批中的进度
            ask_progress = None
            if name == "ask_question":
                ask_seen += 1
                ask_progress = (ask_seen, ask_total)

            tool_span = f"sp_tool_{idx}"
            self.tracer.emit(
                EventType.TOOL_CALL,
                {
                    "name": name,
                    "arguments": args,
                    "action": action,
                    "call_id": call.get("id"),
                },
                session_id=session_id,
                span_id=tool_span,
                parent_span_id=run_span,
            )

            # LLM 生成参数非合法 JSON：把解析错误回填给 AI，让其修正参数后重试
            if parse_err:
                result = ToolResult(ok=False, error=f"{name} 参数解析失败: {parse_err}")
                self._emit_tool_result(name, result, session_id, tool_span, run_span, call.get("id"))
                self.history.append(
                    ChatMessage(role=ChatRole.TOOL, content=result.text, tool_call_id=call.get("id"))
                )
                continue

            if action == PermissionAction.DENY:
                result = ToolResult(ok=False, error=f"permission denied: {name}")
                self._emit_tool_result(name, result, session_id, tool_span, run_span, call.get("id"))
                self.history.append(
                    ChatMessage(role=ChatRole.TOOL, content=result.text, tool_call_id=call.get("id"))
                )
                continue

            # P2：ask 走审批通道（阻塞）；无通道时自动放行并记录事件
            if action == PermissionAction.ASK:
                req = self._request_approval(name, args, path, session_id, tool_span, run_span)
                if req.decision in (None, ApprovalDecision.DENY):
                    result = ToolResult(ok=False, error=f"approval denied: {name}")
                    self._emit_tool_result(name, result, session_id, tool_span, run_span, call.get("id"))
                    self.history.append(
                        ChatMessage(
                            role=ChatRole.TOOL, content=result.text, tool_call_id=call.get("id")
                        )
                    )
                    continue

            tool = self.tools.get(name)
            if tool is None:
                result = ToolResult(ok=False, error=f"工具未注册: {name}")
                self._emit_tool_result(name, result, session_id, tool_span, run_span, call.get("id"))
            else:
                try:
                    result = tool.invoke(
                        ToolContext(
                            workspace=self.workspace,
                            session_id=session_id,
                            meta={
                                "dispatcher": self.dispatcher,
                                "span_id": tool_span,
                                "provider": provider,
                                "model": model,
                                "effort": effort,
                                "attach_image": self._attach_image,
                                "skill_lookup": self._lookup_skill,
                                "tracer": self.tracer,
                                "question_gate": self.questions,
                                "question_progress": ask_progress,
                            },
                        ),
                        **args,
                    )
                except Exception as exc:  # noqa: BLE001
                    try:
                        args_text = json.dumps(args, ensure_ascii=False)
                    except (TypeError, ValueError):
                        args_text = repr(args)
                    result = ToolResult(
                        ok=False,
                        error=f"工具执行异常（{name} 参数 {args_text}）: {exc}",
                    )
                self._emit_tool_result(name, result, session_id, tool_span, run_span, call.get("id"))

            self.history.append(
                ChatMessage(role=ChatRole.TOOL, content=result.text, tool_call_id=call.get("id"))
            )

    def _request_approval(
        self, name: str, args: dict, path: str | None, session_id: str, span: str, run_span: str
    ) -> SimpleNamespace | ApprovalRequest:
        """发起审批：无通道→自动放行；有通道→阻塞等待决议。返回带 decision 的对象。"""
        if self.approvals is None:
            self.tracer.emit(
                EventType.APPROVAL_REQUESTED,
                {"tool": name, "arguments": args, "path": path},
                session_id=session_id,
                span_id=span,
                parent_span_id=run_span,
            )
            self.tracer.emit(
                EventType.APPROVAL_RESOLVED,
                {"tool": name, "decision": "allow", "auto": True},
                session_id=session_id,
                span_id=span,
                parent_span_id=run_span,
            )
            return SimpleNamespace(decision=ApprovalDecision.ALLOW, auto=True, id=None)

        # 自动审批模式：先由决策 agent（auto_approver）评估工具调用。
        # 返回 allow/deny 直接生效；返回 None（无法判断）则回退到人工审批（阻塞 gate）。
        if self.auto_approver is not None:
            decision = self.auto_approver(name, args, path)
            if decision is not None:
                self.tracer.emit(
                    EventType.APPROVAL_RESOLVED,
                    {
                        "tool": name,
                        "decision": decision.value,
                        "auto": True,
                        "auto_agent": True,
                    },
                    session_id=session_id,
                    span_id=span,
                    parent_span_id=run_span,
                )
                return SimpleNamespace(decision=decision, auto=True, id=None)

        req = self.approvals.request(name, args, path)
        if req.status == ApprovalStatus.PENDING:
            self.tracer.emit(
                EventType.APPROVAL_REQUESTED,
                {"tool": name, "arguments": args, "path": path, "request_id": req.id},
                session_id=session_id,
                span_id=span,
                parent_span_id=run_span,
            )
            self.approvals.wait(req)  # 阻塞直到 CLI/Web 决议
        self.tracer.emit(
            EventType.APPROVAL_RESOLVED,
            {
                "tool": name,
                "request_id": req.id,
                "decision": req.decision or ApprovalDecision.DENY,
                "auto": req.auto,
            },
            session_id=session_id,
            span_id=span,
            parent_span_id=run_span,
        )
        return req

    def _emit_tool_result(
        self,
        name: str,
        result: ToolResult,
        session_id: str,
        span: str,
        run_span: str,
        call_id: str | None = None,
    ) -> None:
        ev_type = EventType.TOOL_RESULT if result.ok else EventType.TOOL_ERROR
        self.tracer.emit(
            ev_type,
            {
                "name": name,
                "result": result.output,
                "error": result.error,
                "duration_ms": result.duration_ms,
                "truncated": result.truncated,
                "call_id": call_id,
            },
            session_id=session_id,
            span_id=span,
            parent_span_id=run_span,
        )

    @staticmethod
    def _parse_args(raw: Any) -> tuple[dict[str, Any], str | None]:
        """解析工具参数。返回 (args, error)；error 非空表示参数无法解析（回填给 LLM 修正）。"""
        if isinstance(raw, dict):
            return raw, None
        if isinstance(raw, str):
            if not raw.strip():
                return {}, None
            try:
                return json.loads(raw), None
            except json.JSONDecodeError as exc:
                return {}, f"非合法 JSON（{exc}）: {raw.strip()[:200]}"
        return {}, f"参数类型不支持: {type(raw).__name__}"

    def _check_token_budget(self, session_id: str, run_span: str) -> None:
        if not self.token_budget:
            return
        if self._tokens_in + self._tokens_out > self.token_budget:
            self.tracer.emit(
                EventType.ERROR_RAISED,
                {"message": "超出 token 预算，停止执行", "budget": self.token_budget},
                session_id=session_id,
                span_id=run_span,
            )
            raise RuntimeError("token budget exceeded")

    def one_shot(
        self, prompt: str, session_id: str, *, model: str | None = None, effort: str | None = None
    ) -> str:
        """单次 LLM 调用（不修改 history、不产出会话消息），用于标题生成等辅助任务。

        model/effort：每调用参数（决策 #25）；缺省用 agent 配置。
        """
        messages, _ = build_context(
            self.agent,
            [ChatMessage(role=ChatRole.USER, content=prompt)],
            self.tools,
            self.skills,
            tool_names=self.tools_override,
        )
        eff_model = model or self.agent.model or ""
        eff_effort = effort if effort is not None else self.agent.effort
        eff_provider, eff_model = split_spec(eff_model)
        span = f"sp_one_shot_{short_hash(prompt, 6)}"
        self.tracer.emit(
            EventType.LLM_REQUEST,
            {
                "provider": eff_provider,
                "model": eff_model,
                "effort": eff_effort,
                "task": "one_shot",
                "prompt": prompt,
            },
            session_id=session_id,
            span_id=span,
        )
        buf: list[str] = []
        for chunk in self.router.stream_chat(
            eff_provider,
            messages,
            model=eff_model,
            effort=eff_effort,
            temperature=self.agent.config.temperature,
            max_tokens=self.agent.config.max_tokens or 64,
        ):
            if chunk.text:
                buf.append(chunk.text)
        content = "".join(buf).strip()
        self.tracer.emit(
            EventType.LLM_RESPONSE,
            {"content": content, "task": "one_shot"},
            session_id=session_id,
            span_id=span,
        )
        return content
