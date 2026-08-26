"""SessionManager：会话生命周期管理（P2）。

- 一个会话 = 一个工作区 + 一个工作 agent；持有独立 runtime / EventStream / Tracer / 审批通道；
- send_message 在独立 worker 线程中运行 agent 循环，事件经 EventStream 实时流出；
- 全局并发上限（quota）控制同时运行的会话数，超限排队 / 拒绝（可配置）；
- 审批通道（HITL）：ask 权限命中时阻塞等待 approval.resolve。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Callable

from mira import paths
from mira.api.approval import ApprovalDecision, ApprovalGate
from mira.api.protocol import Session, SessionStatus
from mira.api.questions import QuestionGate
from mira.api.quota import SessionQuota
from mira.api.stream import EventStream, StreamTracer
from mira.core.providers.base import ChatMessage, ChatRole
from mira.util import utcnow_iso
from mira.core.agents.base import BaseAgent
from mira.core.agents.registry import AgentRegistry
from mira.core.config.mutation import update_config
from mira.core.config.queries import get_config, get_models
from mira.core.config.schemas import AgentRole, ApprovalMode
from mira.core.config.store import ConfigStore
from mira.core.mcp.manager import McpManager
from mira.core.orchestration import TaskDispatcher
from mira.core.providers.router import ProviderRouter
from mira.core.runtime import AgentRuntime
from mira.core.skills.loader import SkillLoader, scan_skill_dir
from mira.core.skills.registry import SkillRegistry
from mira.core.tools.permission import PermissionChecker
from mira.core.tools.registry import ToolRegistry
from mira.core.tools.builtin.dispatch import DispatchTaskTool
from mira.telemetry.events import EventType
from mira.telemetry.store import EventStore
from mira.telemetry.tracer import CompositeTracer, EventLogTracer


def parse_approver_decision(text: str) -> ApprovalDecision | None:
    """解析自动审批决策 agent 的输出：allow/deny → 对应决策；其它（含 fallback/无法解析）→ None（回退人工）。"""
    out = (text or "").strip().lower()
    if out.startswith("allow"):
        return ApprovalDecision.ALLOW
    if out.startswith("deny"):
        return ApprovalDecision.DENY
    return None


class SessionManager:
    def __init__(
        self,
        store: ConfigStore | None = None,
        *,
        router: ProviderRouter | None = None,
    ) -> None:
        self.store = store or ConfigStore()
        self._router = router
        self._skills = SkillLoader.build(
            self.store.skills(),
            [paths.agents_skills_dir(), paths.mira_skills_dir()],
        )
        self._agents = AgentRegistry.from_store(self.store, self._skills)
        self._sessions: dict[str, Session] = {}
        self._runtimes: dict[str, AgentRuntime] = {}
        self._streams: dict[str, EventStream] = {}
        self._tracers: dict[str, CompositeTracer] = {}
        self._approvals: dict[str, ApprovalGate] = {}
        self._questions: dict[str, QuestionGate] = {}  # 提问通道（ask_question 工具挂起问题）
        self._mcp: dict[str, McpManager] = {}  # P3：每会话 MCP 连接（决策 #8d）
        self._stop_events: dict[str, threading.Event] = {}  # 停止生成标志（置位后中断当前回复）
        self._queued: dict[str, list[dict]] = {}  # 运行中插入的排队消息（FIFO；interrupt 插队到最前）
        self._lock = threading.RLock()
        self._quota = SessionQuota(self.store.runtime().session.max_concurrent_sessions)

    # ── 会话生命周期 ─────────────────────────────────────────

    def create_session(
        self,
        workspace: str | Path,
        agent_type: str = "main",
        model: str | None = None,
    ) -> Session:
        runtime_cfg = self.store.runtime()
        if not self._agents.has(agent_type):
            raise ValueError(f"未注册的 agent: {agent_type!r}（可用: {self._agents.ids()}）")
        agent: BaseAgent = self._agents.get(agent_type)

        ws = str(workspace)
        # 模型以 {provider}/{model} 规格串标识（决策 #26）：provider 由模型推导，不单独存储
        model = model or agent.model or runtime_cfg.session.default_model

        # workspace 元数据边车：记录原始路径，供 Web 前端识别/创建会话
        meta_path = paths.workspace_meta_path(ws)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(
            json.dumps({"path": ws, "created_at": utcnow_iso()}, ensure_ascii=False),
            encoding="utf-8",
        )

        with self._lock:
            now = utcnow_iso()
            sess = Session(workspace=ws, agent_type=agent_type, model=model, created_at=now, updated_at=now)
            stream = EventStream(sess.id)
            tracer = CompositeTracer(
                EventLogTracer(EventStore(paths.sessions_dir(ws))),
                StreamTracer(stream),
            )
            tracer.emit(
                EventType.SESSION_CREATED,
                {
                    "session_id": sess.id,
                    "workspace": paths.workspace_id(ws),
                    "agent": agent_type,
                    "model": model,
                },
                session_id=sess.id,
            )
            gate = ApprovalGate(sess.id, on_state_change=self._on_approval_state)
            qgate = QuestionGate(sess.id, on_state_change=self._on_question_state)
            self._sessions[sess.id] = sess
            self._streams[sess.id] = stream
            self._tracers[sess.id] = tracer
            self._approvals[sess.id] = gate
            self._questions[sess.id] = qgate
        return sess

    def fork_session(self, source_id: str, until_seq: int) -> Session:
        """分叉：创建新 session，并把源会话 until_seq **之前**（不含该条）的对话复制为初始上下文。"""
        with self._lock:
            if source_id not in self._sessions:
                restored = self._restore_session(source_id)
                if restored is None:
                    raise KeyError(f"未知会话: {source_id!r}")
            source = self._sessions[source_id]
            if source_id in self._streams:
                events = self._streams[source_id].snapshot()
            else:
                events = list(
                    EventStore(paths.sessions_dir(source.workspace)).read(source_id)
                )
            keep = [
                e
                for e in events
                if e.seq < until_seq and e.type != EventType.SESSION_CREATED
            ]
            if not keep:
                raise ValueError("该消息之前没有可复制的历史")
            new = self.create_session(source.workspace, source.agent_type, source.model)
            tracer = self._tracers[new.id]
            for e in keep:
                tracer.emit(
                    e.type,
                    e.payload,
                    session_id=new.id,
                    span_id=e.span_id,
                    parent_span_id=e.parent_span_id,
                )
            try:
                history, usage = self._rebuild_history(keep)
                self._runtimes[new.id] = self._build_runtime(
                    new, initial_history=history, initial_usage=usage
                )
            except Exception:  # noqa: BLE001
                pass
            return new

    def get(self, session_id: str) -> Session:
        try:
            return self._sessions[session_id]
        except KeyError:
            raise KeyError(f"未知会话: {session_id!r}") from None

    def list_sessions(self) -> list[Session]:
        with self._lock:
            return list(self._sessions.values())

    def events(self, session_id: str) -> EventStream:
        try:
            return self._streams[session_id]
        except KeyError:
            raise KeyError(f"未知会话: {session_id!r}") from None

    # ── 执行 ─────────────────────────────────────────────────

    def send_message(
        self,
        session_id: str,
        text: str,
        *,
        model: str,
        effort: str | None = None,
        attachments: list[str] | None = None,
    ) -> threading.Thread | None:
        """在独立线程中运行一次 agent 循环，立即返回线程句柄；超配额且不允许排队时拒绝。

        model：本轮回复使用的模型（每回复必带，决策 #25；session 不绑定 model）。
        effort：reasoning 模型思考强度（low/medium/high / off），前端每轮随消息发送。
        attachments：用户选中的文件绝对路径列表，作为本轮的前导 user 消息发给 AI。
        """
        if session_id not in self._sessions and self._restore_session(session_id) is None:
            raise KeyError(f"未知会话: {session_id!r}")
        self._stop_events.setdefault(session_id, threading.Event()).clear()
        runtime_cfg = self.store.runtime()
        if not runtime_cfg.session.queue_on_quota and not self._quota.can_acquire():
            self._tracers[session_id].emit(
                EventType.ERROR_RAISED,
                {"message": "已达全局并发上限，已拒绝本次请求", "usage": self._quota.usage()},
                session_id=session_id,
            )
            self._emit_status(self._sessions[session_id], "failed")
            return None
        thread = threading.Thread(
            target=self._run_turn,
            args=(session_id, text, model, effort, attachments or []),
            daemon=True,
        )
        thread.start()
        return thread

    def enqueue_message(
        self,
        session_id: str,
        text: str,
        *,
        model: str,
        effort: str | None = None,
        interrupt: bool = False,
        attachments: list[str] | None = None,
    ) -> dict:
        """AI 回复期间插入新消息。

        interrupt=True：立即斧正——停止当前回复，把新消息插到队列最前，当前轮结束后优先处理；
        interrupt=False：排队——当前一轮回复结束后再把新消息加入上下文，多条按 FIFO 串行。
        attachments：选中的文件绝对路径列表，作为本轮的前导 user 消息发给 AI。
        """
        if session_id not in self._sessions and self._restore_session(session_id) is None:
            raise KeyError(f"未知会话: {session_id!r}")
        session = self._sessions[session_id]
        entry = {"text": text, "model": model, "effort": effort, "attachments": attachments or []}
        with self._lock:
            q = self._queued.setdefault(session_id, [])
            if interrupt:
                q.insert(0, entry)
            else:
                q.append(entry)
        if interrupt:
            self.stop_session(session_id)  # 尽快进入可插入点
        if session.status == SessionStatus.IDLE:
            self._drain_queue(session_id)
        return {"queued": len(q)}

    def _drain_queue(self, session_id: str) -> None:
        """取出队列第一条并按需启动一轮（串行：完成一个才处理下一个）。"""
        with self._lock:
            q = self._queued.get(session_id)
            if not q:
                return
            entry = q.pop(0)
        thread = threading.Thread(
            target=self._run_turn,
            args=(
                session_id,
                entry["text"],
                entry["model"],
                entry["effort"],
                entry.get("attachments") or [],
            ),
            daemon=True,
        )
        thread.start()

    def _restore_session(self, session_id: str) -> Session | None:
        """从磁盘事件日志恢复历史会话，使其可以继续对话。"""
        with self._lock:
            if session_id in self._sessions:
                return self._sessions[session_id]

            root = paths.workspaces_dir()
            if not root.exists():
                return None
            for workspace_dir in root.iterdir():
                if not workspace_dir.is_dir():
                    continue
                store = EventStore(workspace_dir / "sessions")
                if not store.session_dir(session_id).is_dir():
                    continue
                events = list(store.read(session_id))
                created = next(
                    (event for event in events if event.type == EventType.SESSION_CREATED),
                    None,
                )
                if created is None:
                    continue
                workspace = ""
                workspace_meta = workspace_dir / "workspace.json"
                if workspace_meta.exists():
                    try:
                        workspace = json.loads(
                            workspace_meta.read_text(encoding="utf-8")
                        ).get("path", "")
                    except (OSError, json.JSONDecodeError):
                        workspace = ""
                if not workspace:
                    continue

                title = ""
                updated_at = ""
                session_meta = paths.session_meta_path(workspace, session_id)
                if session_meta.exists():
                    try:
                        meta_data = json.loads(session_meta.read_text(encoding="utf-8"))
                        title = meta_data.get("title", "")
                        updated_at = meta_data.get("updated_at", "")
                    except (OSError, json.JSONDecodeError):
                        title = ""
                payload = created.payload
                session = Session(
                    id=session_id,
                    workspace=workspace,
                    agent_type=payload.get("agent", "main"),
                    model=payload.get("model", ""),
                    title=title,
                    updated_at=updated_at or created.ts,
                    created_at=created.ts,
                )
                stream = EventStream(session_id)
                for event in events:
                    stream.append(event)
                tracer = CompositeTracer(EventLogTracer(store), StreamTracer(stream))
                tracer._seqs[session_id] = max((event.seq for event in events), default=0)
                self._sessions[session_id] = session
                self._streams[session_id] = stream
                self._tracers[session_id] = tracer
                self._approvals[session_id] = ApprovalGate(
                    session_id, on_state_change=self._on_approval_state
                )
                self._questions[session_id] = QuestionGate(
                    session_id, on_state_change=self._on_question_state
                )
                # 直接重建 runtime（含 LLM 历史上下文），让会话在 _sessions/_runtimes 中完整可用；
                # 构建失败（如 MCP/provider 配置问题）不阻断恢复，_run_turn 会重试并统一处理
                try:
                    history, usage = self._rebuild_history(events)
                    self._runtimes[session_id] = self._build_runtime(
                        session, initial_history=history, initial_usage=usage
                    )
                except Exception:  # noqa: BLE001
                    pass
                return session
        return None

    def _rebuild_history(self, events) -> tuple[list[ChatMessage], tuple[int, int, float]]:
        """从历史事件重建 LLM 对话历史与累计用量（继续历史会话时作为上下文种子）。

        - user.message → USER；llm.response → ASSISTANT（含 reasoning_content / tool_calls）；
        - tool.result / tool.error → TOOL（按 llm.response 的 tool_calls 顺序配对 tool_call_id）；
        - usage 累计用于 token 预算连续。
        """
        history: list[ChatMessage] = []
        pending_ids: list[str] = []
        tokens_in = tokens_out = 0
        cost = 0.0
        for ev in events:
            t, p = ev.type, ev.payload
            if t == EventType.USER_MESSAGE:
                history.append(ChatMessage(role=ChatRole.USER, content=p.get("content", "")))
            elif t == EventType.LLM_RESPONSE:
                if p.get("task"):
                    # 决策（approver）/ 标题（summarizer）等辅助 one_shot 调用也写入同一会话日志，
                    # 但不属于主对话：混入会把 assistant(tool_calls) 与其 tool 结果隔开，
                    # 导致 DeepSeek 报 "insufficient tool messages following tool_calls"。
                    continue
                content = p.get("content") or ""
                reasoning = p.get("reasoning_content") or ""
                tool_calls = p.get("tool_calls")
                if content or reasoning or tool_calls:
                    msg = ChatMessage(
                        role=ChatRole.ASSISTANT,
                        content=content,
                        reasoning_content=reasoning,
                    )
                    if tool_calls:
                        msg.tool_calls = tool_calls
                        pending_ids = [tc.get("id") for tc in tool_calls if tc.get("id")]
                    history.append(msg)
                usage = p.get("usage") or {}
                tokens_in += usage.get("input_tokens") or 0
                tokens_out += usage.get("output_tokens") or 0
                cost += usage.get("cost_usd") or 0.0
            elif t in (EventType.TOOL_RESULT, EventType.TOOL_ERROR):
                out = (p.get("result") or p.get("error") or "").strip()
                call_id = pending_ids.pop(0) if pending_ids else None
                history.append(ChatMessage(role=ChatRole.TOOL, content=out, tool_call_id=call_id))
        return history, (tokens_in, tokens_out, cost)

    def _run_turn(
        self,
        session_id: str,
        text: str,
        model: str,
        effort: str | None = None,
        attachments: list[str] | None = None,
    ) -> None:
        session = self._sessions[session_id]
        # 决策 #25：model/effort 是每回复参数，session 不绑定、不更新 session.model
        tracer = self._tracers[session_id]
        self._stop_events.setdefault(session_id, threading.Event()).clear()
        self._quota.acquire()  # 排队等待并发槽位（超限时阻塞或已在 send_message 拒绝）
        try:
            session.status = SessionStatus.RUNNING
            self._emit_status(session, "running")
            runtime = self._build_runtime(session)
            extra_history = None
            if attachments:
                # 前导 user 消息：告知 AI 用户选中的文件绝对路径
                extra_history = [
                    ChatMessage(
                        role=ChatRole.USER,
                        content="用户选中了文件：\n" + "\n".join(attachments),
                    )
                ]
            runtime.run(
                text, session_id, model=model, effort=effort, extra_history=extra_history
            )
            self._maybe_generate_title(session, runtime)
            self._touch(session)  # 新对话/回复 → 更新最近交互时间（会话列表倒序）
            session.status = SessionStatus.IDLE
            self._emit_status(session, "idle")
        except Exception as exc:  # noqa: BLE001
            session.status = SessionStatus.FAILED
            tracer.emit(
                EventType.ERROR_RAISED,
                {"message": str(exc)},
                session_id=session_id,
            )
            self._emit_status(session, "failed")
        finally:
            self._quota.release()
            self._drain_queue(session_id)  # 处理排队消息（含斧正插入）

    def _dispatchable_agents(self, caller: BaseAgent) -> list[dict[str, str]]:
        """当前可自动分派给主 agent 的子 agent（dispatch=auto 且 role=sub，排除调用者自己）。

        动态来自 agents registry（配置即注册）：新增/修改子 agent 配置后主 agent 自动感知。
        """
        out: list[dict[str, str]] = []
        for a in self._agents.list():
            cfg = a.config
            if cfg.id == caller.config.id:
                continue
            if cfg.role == AgentRole.SUB and cfg.dispatch == "auto":
                out.append(
                    {
                        "id": cfg.id,
                        "name": cfg.name or cfg.id,
                        "description": cfg.description,
                    }
                )
        return out

    def _build_auto_approver(self, session: Session) -> Callable[[str, dict, str | None], ApprovalDecision | None] | None:
        """自动审批（approval.mode=auto）的决策器：用 auto_agent 评估 ask 命中的工具调用。

        返回 (tool, args, path) -> ApprovalDecision | None：
        - allow/deny：决策 agent 给出的结论，直接生效；
        - None：无法判断（决策 agent 未配置/未注册/调用失败，或输出 fallback）→ 回退人工审批；
        - 未启用 auto 模式 → None（保持原有人工审批流程）。
        特例：auto 模式但 auto_agent 为空 → 保持旧行为（直接放行）。
        """
        cfg = self.store.runtime().approval
        if cfg.mode != ApprovalMode.AUTO:
            return None
        agent_id = (cfg.auto_agent or "").strip()
        if not agent_id:
            return lambda name, args, path: ApprovalDecision.ALLOW
        if not self._agents.has(agent_id):
            return None
        agent = self._agents.get(agent_id)
        router = self._router or ProviderRouter.from_configs(self.store.providers())
        approver_rt = AgentRuntime(
            agent=agent,
            router=router,
            tools=ToolRegistry.with_builtins(),
            permissions=PermissionChecker(agent.config.permission.rules, mode=ApprovalMode.ASK),
            tracer=self._tracers[session.id],
            workspace=session.workspace,
            skills=self._skills,
            approvals=None,  # 决策 agent 自身不再触发审批
            tools_override=agent.enabled_tools(),
            max_steps=1,
        )
        model = (session.model or agent.model or "").strip() or None

        def decide(name: str, args: dict, path: str | None) -> ApprovalDecision | None:
            parts = [f"工具: {name}", f"参数: {json.dumps(args, ensure_ascii=False)}"]
            if path:
                parts.append(f"路径: {path}")
            prompt = "请审批以下工具调用（只输出 allow / deny / fallback 之一）：\n" + "\n".join(parts)
            try:
                out = approver_rt.one_shot(prompt, session.id, model=model)
            except Exception:  # noqa: BLE001
                return None
            return parse_approver_decision(out)

        return decide

    def _skills_for_workspace(self, workspace: str | Path) -> SkillRegistry:
        """全局技能 + 该工作目录下 .skills/ 的项目级技能（项目级覆盖同名）。"""
        ws = scan_skill_dir(paths.workspace_skills_dir(workspace))
        if not ws:
            return self._skills
        merged = {s.id: s for s in self._skills.list()}
        merged.update(ws)
        return SkillRegistry().register_many(list(merged.values()))

    def _build_runtime(
        self,
        session: Session,
        *,
        initial_history: list[ChatMessage] | None = None,
        initial_usage: tuple[int, int, float] | None = None,
    ) -> AgentRuntime:
        with self._lock:
            if session.id in self._runtimes:
                return self._runtimes[session.id]
            agent = self._agents.get(session.agent_type)
            tools = ToolRegistry.with_builtins()
            # P3：dispatch=auto 的 agent 注册 dispatch_task 工具（可选目标动态来自 registry）
            if agent.config.dispatch == "auto":
                tools.register(
                    DispatchTaskTool(available=self._dispatchable_agents(agent))
                )
            # P3：MCP 工具（决策 #8d：每会话独立连接 / 释放）
            mcp = self._mcp.get(session.id)
            if mcp is None:
                mcp = McpManager(self.store.mcp_servers())
                mcp.connect_all()
                self._mcp[session.id] = mcp
            mcp_tools = mcp.tools_for(agent)
            for t in mcp_tools:
                tools.register(t)
            effective = agent.enabled_tools() + [t.name for t in mcp_tools]
            # 启用了技能的 agent 自动获得 skill 工具（按需取技能全文，system prompt 只列索引）
            if agent.enabled_skills() and "skill" not in effective:
                effective.append("skill")
            permissions = PermissionChecker(
                agent.config.permission.rules, mode=self.store.runtime().approval.mode
            )
            router = self._router or ProviderRouter.from_configs(self.store.providers())
            auto_approver = self._build_auto_approver(session)
            skills = self._skills_for_workspace(session.workspace)
            dispatcher = TaskDispatcher(
                store=self.store,
                agents=self._agents,
                router=router,
                skills=skills,
                tracer=self._tracers[session.id],
                workspace=session.workspace,
                approvals=self._approvals[session.id],
                mcp_manager=mcp,
                auto_approver=auto_approver,
            )
            runtime = AgentRuntime(
                agent=agent,
                router=router,
                tools=tools,
                permissions=permissions,
                tracer=self._tracers[session.id],
                workspace=session.workspace,
                skills=skills,
                token_budget=agent.config.token_budget,
                approvals=self._approvals[session.id],
                questions=self._questions[session.id],
                auto_approver=auto_approver,
                tools_override=effective,
                dispatcher=dispatcher,
                stop_event=self._stop_events.get(session.id),
            )
            # 历史会话：把重建的对话历史作为 LLM 上下文种子，并恢复 token 用量（预算连续性）
            if initial_history:
                runtime.history = list(initial_history)
                if initial_usage:
                    runtime._tokens_in, runtime._tokens_out, runtime._cost_usd = initial_usage
            self._runtimes[session.id] = runtime
            return runtime

    def close_session(self, session_id: str) -> None:
        with self._lock:
            stream = self._streams.pop(session_id, None)
            if stream:
                stream.close()
            self._sessions.pop(session_id, None)
            self._runtimes.pop(session_id, None)
            self._tracers.pop(session_id, None)
            self._approvals.pop(session_id, None)
            self._questions.pop(session_id, None)
            self._stop_events.pop(session_id, None)
            self._queued.pop(session_id, None)
            mcp = self._mcp.pop(session_id, None)
            if mcp:
                mcp.close()

    def stop_session(self, session_id: str) -> None:
        """请求停止当前正在生成的回复（幂等）：置停止标志 + 中断待审批。"""
        ev = self._stop_events.get(session_id)
        if ev is not None:
            ev.set()
        gate = self._approvals.get(session_id)
        if gate is not None:
            gate.interrupt()
        qgate = self._questions.get(session_id)
        if qgate is not None:
            qgate.interrupt()

    def resolve_approval(self, session_id: str, request_id: str, decision: str) -> dict:
        """审批决议：allow / deny / always。"""
        gate = self._approvals.get(session_id)
        if gate is None:
            raise KeyError(f"未知会话: {session_id!r}")
        return gate.resolve(request_id, decision).model_dump()

    def pending_approvals(self, session_id: str) -> list[dict]:
        gate = self._approvals.get(session_id)
        return [r.model_dump() for r in gate.pending()] if gate else []

    def answer_question(self, session_id: str, question_id: str, answer: str) -> dict:
        """用户作答：解除 ask_question 工具阻塞，答案作为工具结果回填给 LLM。"""
        gate = self._questions.get(session_id)
        if gate is None:
            raise KeyError(f"未知会话: {session_id!r}")
        return gate.answer(question_id, answer).model_dump()

    def pending_questions(self, session_id: str) -> list[dict]:
        gate = self._questions.get(session_id)
        return [q.model_dump() for q in gate.pending()] if gate else []

    def quota_usage(self) -> dict:
        return self._quota.usage()

    def available_agents(self) -> list[dict]:
        return [{"id": a.id, "name": a.name} for a in self._agents.list()]

    def available_providers(self) -> list[dict]:
        return [
            {"id": p.id, "type": p.type, "base_url": p.base_url}
            for p in self.store.providers()
        ]

    # ── 配置中心（决策 #10）──────────────────────────────────

    def get_config(self) -> dict:
        """读取全部配置分区（供配置中心渲染）。"""
        return get_config(self.store)

    def update_config(self, section: str, data: dict) -> dict:
        """校验并写回指定配置分区；写回后热重载。"""
        result = update_config(self.store, section, data)
        self.reload_config()
        return result

    def get_models(
        self, provider_id: str | None = None, provider_type: str | None = None
    ) -> dict:
        """聚合可用模型（含 thinking 能力）；provider_type=按 litellm 前缀查 models.dev。"""
        return get_models(self.store, provider_id, provider_type=provider_type)

    def reload_config(self) -> None:
        """配置中心写回后热重载：重建 agent / skill 注册表与并发配额。

        活跃会话保持各自的 runtime（继续用旧配置运行）；新建会话使用新配置。
        """
        self._skills = SkillLoader.build(
            self.store.skills(),
            [paths.agents_skills_dir(), paths.mira_skills_dir()],
        )
        self._agents = AgentRegistry.from_store(self.store, self._skills)
        self._quota = SessionQuota(self.store.runtime().session.max_concurrent_sessions)

    def _on_approval_state(self, session_id: str, waiting: bool) -> None:
        """审批挂起/解除时更新会话状态（waiting/running）。"""
        session = self._sessions.get(session_id)
        if not session:
            return
        session.status = SessionStatus.WAITING if waiting else SessionStatus.RUNNING
        self._emit_status(session, session.status.value)

    def _on_question_state(self, session_id: str, waiting: bool) -> None:
        """提问挂起/解除时更新会话状态（waiting/running）。"""
        session = self._sessions.get(session_id)
        if not session:
            return
        session.status = SessionStatus.WAITING if waiting else SessionStatus.RUNNING
        self._emit_status(session, session.status.value)

    def _emit_status(self, session: Session, status: str) -> None:
        self._tracers[session.id].emit(
            EventType.SESSION_STATUS,
            {"status": status, "session_id": session.id, "title": session.title},
            session_id=session.id,
        )

    # ── 会话标题（首轮后由配置式 summarizer agent 生成）──

    def _maybe_generate_title(self, session: Session, main_runtime: AgentRuntime) -> None:
        """首轮结束后：用配置式 summarizer agent 基于首轮对话生成会话标题。"""
        if session.title or not self._agents.has("summarizer"):
            return
        history = main_runtime.history
        user = next((m.content for m in history if m.role == ChatRole.USER), "")
        reply = next((m.content for m in reversed(history) if m.role == ChatRole.ASSISTANT), "")
        prompt = f"用户：{user}\n助手：{reply}".strip()
        if not prompt:
            return
        try:
            summarizer = self._build_summarizer_runtime(session)
            title = summarizer.one_shot(prompt, session.id)
        except Exception:  # noqa: BLE001
            title = ""
        title = title.strip().strip('"“”「」').strip()
        # 标题应简短（summarizer 配置要求 ≤20 字）；输出异常/过长时回退首条用户消息
        if not title or len(title) > 30:
            title = user.strip()[:20] if user else ""
        if title:
            session.title = title[:60]
            self._persist_meta(session)
            self._tracers[session.id].emit(
                EventType.SESSION_TITLED,
                {"session_id": session.id, "title": session.title},
                session_id=session.id,
            )

    def _build_summarizer_runtime(self, session: Session) -> AgentRuntime:
        agent = self._agents.get("summarizer")
        tools = ToolRegistry.with_builtins()
        permissions = PermissionChecker(
            agent.config.permission.rules, mode=self.store.runtime().approval.mode
        )
        router = self._router or ProviderRouter.from_configs(self.store.providers())
        return AgentRuntime(
            agent=agent,
            router=router,
            tools=tools,
            permissions=permissions,
            tracer=self._tracers[session.id],
            workspace=session.workspace,
            skills=self._skills,
            approvals=None,
        )

    def _touch(self, session: Session) -> None:
        """标记最近交互时间（新对话/回复）并落盘，会话列表按此倒序。"""
        session.updated_at = utcnow_iso()
        self._persist_meta(session)

    def _persist_meta(self, session: Session) -> None:
        """把 title / updated_at 落盘到 sessions/<sid>/meta.json（重启后仍可显示/排序）。"""
        try:
            meta_path = paths.session_meta_path(session.workspace, session.id)
            meta_path.parent.mkdir(parents=True, exist_ok=True)
            data: dict = {}
            if meta_path.exists():
                try:
                    data = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    data = {}
            if session.title:
                data["title"] = session.title
            if session.updated_at:
                data["updated_at"] = session.updated_at
            meta_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
