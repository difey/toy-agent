"""Shared in-memory application state and client-facing projections."""

import asyncio
import json
import os
import traceback

from nano_claude.core.agent import Agent
from nano_claude.core.diff_service import (
    _get_git_head_hash,
    cleanup_checkpoints,
    detect_file_changes,
    save_checkpoint,
    take_snapshot,
)
from nano_claude.core.interaction_state import InteractionState
from nano_claude.core.message import DiffSummaryMessage, ToolCall
from nano_claude.core.provider_service import (
    ProviderInfo,
    ProviderManager,
)
from nano_claude.core.session import Session, save_current
from nano_claude.core.session_runtime import SessionRuntime
from nano_claude.core.workspace import build_workspace_view
from nano_claude.infra.bootstrap import build_agent


class AppState:
    """Shared mutable state for the web UI server."""

    def __init__(self):
        self.agent: Agent | None = None
        self.cwd: str = ""
        self.session_runtime = SessionRuntime(lambda: self.cwd, lambda: self.agent)
        self.interaction = InteractionState()
        self._sse_queues: dict[str, asyncio.Queue] = {}
        self._running_response_id: str | None = None
        self._running: bool = False
        self._running_task: asyncio.Task | None = None
        self._last_error: str | None = None
        self.providers_mgr = ProviderManager()

    @property
    def session(self) -> Session:
        return self.session_runtime.session

    def initialize(self, cwd: str) -> None:
        self.cwd = cwd
        self.agent = build_agent(cwd=self.cwd, mode="build")
        self.session_runtime.initialize()
        self._load_providers()

    def _status(self) -> str:
        if self.interaction.pending_permission is not None:
            return "awaiting_permission"
        if self.interaction.pending_question is not None:
            return "awaiting_question"
        if self._running:
            return "running"
        if self._last_error:
            return "error"
        return "idle"

    def clear_error(self) -> None:
        self._last_error = None

    def set_error(self, message: str) -> None:
        self._last_error = message

    def app_view(self) -> dict:
        return {
            "cwd": self.cwd,
            "mode": self.agent.mode if self.agent else "build",
            "status": self._status(),
            "setup_needed": self.agent is None,
            "active_model": self.agent.model if self.agent else None,
            "active_provider": self.agent.provider if self.agent else None,
            "last_error": self._last_error,
        }

    def session_catalog_view(self) -> dict:
        return {
            "sessions": self.session_runtime.sessions_list(),
        }

    def workspace_view(self, active_diff: str | None = None) -> dict:
        return build_workspace_view(
            self.cwd,
            self.session_runtime.diff_summaries(),
            active_diff=active_diff,
        )

    def current_view(self, active_diff: str | None = None) -> dict:
        return {
            "app": self.app_view(),
            "session_meta": self.session_runtime.current_meta(),
            "session_catalog": self.session_catalog_view(),
            "conversation": {
                "timeline": self.session_runtime.timeline(),
            },
            "interaction": self.interaction.view(),
            "workspace": self.workspace_view(active_diff),
        }

    def current_info(self) -> dict:
        return self.current_view()

    def _find_session_by_name(self, name: str) -> str | None:
        return self.session_runtime._find_session_by_name(name)

    def _refresh_sessions(self) -> list[str]:
        return self.session_runtime._refresh_sessions()

    def sessions_list(self) -> list[dict]:
        return self.session_runtime.sessions_list()

    def load_session_by_name(self, name: str) -> str | None:
        return self.session_runtime.load_session_by_name(name)

    def delete_session_by_name(self, name: str) -> str | None:
        return self.session_runtime.delete_session_by_name(name)

    def fork_session(self, message_api_index: int) -> dict:
        self.session_runtime.fork_session(message_api_index)
        return self.current_view()

    def rollback_session(self, message_api_index: int) -> dict:
        result = self.session_runtime.rollback_session(message_api_index)
        current = self.current_view()
        current["skipped_files"] = result.get("skipped_files", [])
        current["errors"] = result.get("errors", [])
        current["rollback_hash_error"] = result.get("rollback_hash_error", False)
        return current

    def new_session(self) -> None:
        self.session_runtime.new_session()

    def add_diff_summary(self, checkpoint_filename: str, summary: dict) -> None:
        self.session_runtime.add_diff_summary(checkpoint_filename, summary)

    def respond_permission(self, decision: str) -> None:
        self.interaction.respond_permission(decision)

    def respond_question(self, answer: str | list[str]) -> None:
        self.interaction.respond_question(answer)

    def stop_running(self) -> bool:
        """Cancel the current AI response task. Returns True if there was a running task."""
        if not self._running or self._running_task is None:
            return False
        self._running_task.cancel()
        return True

    def get_plan_doc(self, filename: str | None = None) -> dict:
        """Read a plan document from the session's plan directory."""
        from nano_claude.core.workspace import get_plan_doc as _get_plan_doc
        return _get_plan_doc(self.cwd, filename)

    def resolve_latest_plan(self) -> None:
        """Rename the latest .md plan to .md.resolved."""
        from nano_claude.core.workspace import resolve_latest_plan as _resolve_latest_plan
        _resolve_latest_plan(self.cwd)

    def _load_providers(self) -> None:
        self.providers_mgr.get_all()  # warm the cache

    def get_providers(self) -> dict[str, ProviderInfo]:
        """Reload providers from disk and return the latest mapping."""
        return self.providers_mgr.get_all()

    async def add_provider(
        self,
        name: str,
        provider_type: str,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> ProviderInfo:
        """Add a new provider via ProviderManager. Validates, fetches models, persists."""
        return await self.providers_mgr.add(name, provider_type, api_key, base_url)

    def remove_provider(self, name: str) -> None:
        self.providers_mgr.remove(name)

    async def refresh_provider(self, name: str) -> ProviderInfo:
        return await self.providers_mgr.refresh(name)

    async def update_provider(
        self,
        name: str,
        *,
        new_type: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> ProviderInfo:
        return await self.providers_mgr.update(name, new_type=new_type, api_key=api_key, base_url=base_url)

    def set_provider_models(self, name: str, models: list[str]) -> ProviderInfo:
        return self.providers_mgr.set_models(name, models)

    def get_provider(self, name: str) -> ProviderInfo:
        return self.providers_mgr.get(name)

    def provider_exists(self, name: str) -> bool:
        return self.providers_mgr.exists(name)

    def create_sse_queue(self, response_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._sse_queues[response_id] = q
        self._running_response_id = response_id
        return q

    def get_sse_queue(self, response_id: str) -> asyncio.Queue | None:
        return self._sse_queues.get(response_id)

    def remove_sse_queue(self, response_id: str) -> None:
        self._sse_queues.pop(response_id, None)
        if self._running_response_id == response_id:
            self._running_response_id = None

    async def push_event(self, event: str, data: dict) -> None:
        if self._running_response_id:
            q = self._sse_queues.get(self._running_response_id)
            if q:
                await q.put((event, data))

    # ── Chat orchestration ──────────────────────────────────────────────

    async def run_chat(self) -> str:
        """Schedule the agent to run in background. Returns the response_id immediately."""
        if self._running:
            raise RuntimeError("已有正在运行的回复，请先停止当前回复")

        session = self.session

        self._running = True

        response_id = f"chat_{id(session)}_{len(session.messages)}"
        self.create_sse_queue(response_id)

        task = asyncio.ensure_future(self._execute_chat(response_id))
        self._running_task = task
        return response_id

    async def _execute_chat(self, response_id: str) -> None:
        """Actually execute the agent chat in the background, pushing SSE events."""
        agent = self.agent
        session = self.session
        cwd = self.cwd

        # Set up agent callbacks to push events
        original_on_text = agent.on_text_delta
        original_on_tool_start = agent.on_tool_start
        original_on_tool_end = agent.on_tool_end
        original_permission = agent.permission_callback
        original_ask_user = agent.ask_user_callback
        original_on_event = agent.on_event_callback

        async def on_text(text: str):
            await self.push_event("message", {"role": "assistant", "type": "text", "content": text})
            if original_on_text:
                result = original_on_text(text)
                if asyncio.iscoroutine(result):
                    await result

        async def on_tool_start(call: ToolCall):
            await self.push_event("message", {
                "role": "assistant",
                "type": "tool_start",
                "name": call.name,
                "arguments": call.arguments,
            })
            if original_on_tool_start:
                result = original_on_tool_start(call)
                if asyncio.iscoroutine(result):
                    await result

        async def on_tool_end(name: str, title: str, output: str, metadata: dict | None = None):
            event_data = {
                "role": "tool",
                "type": "tool_result",
                "name": name,
                "title": title,
                "content": output,
            }
            if metadata and "flow_id" in metadata:
                event_data["flow_id"] = metadata["flow_id"]
            await self.push_event("message", event_data)
            if original_on_tool_end:
                result = original_on_tool_end(name, title, output, metadata)
                if asyncio.iscoroutine(result):
                    await result

        async def permission_callback(tool: str, target: str, resolved_path: str) -> str:
            loop = asyncio.get_running_loop()
            future = loop.create_future()
            pending = self.interaction.begin_permission(
                future,
                tool=tool,
                target=target,
                resolved_path=resolved_path,
                cwd=cwd,
            )
            await self.push_event("permission_request", {
                "request_id": pending["request_id"],
                "tool": tool,
                "target": target,
                "resolved_path": resolved_path,
                "cwd": cwd,
            })
            try:
                result = await asyncio.wait_for(future, timeout=120)
                return result
            except asyncio.TimeoutError:
                return "deny"
            finally:
                self.interaction.clear_permission()

        async def ask_user_callback(header: str, question: str, options: list[dict], multiple: bool) -> list[str]:
            loop = asyncio.get_running_loop()
            future = loop.create_future()
            pending = self.interaction.begin_question(
                future,
                header=header,
                question=question,
                options=options,
                multiple=multiple,
            )
            await self.push_event("question", {
                "request_id": pending["request_id"],
                "header": header,
                "question": question,
                "options": options,
                "multiple": multiple,
            })
            try:
                result = await asyncio.wait_for(future, timeout=300)
                return result
            except asyncio.TimeoutError:
                return ["(skipped)"]
            finally:
                self.interaction.clear_question()

        async def on_event(event_type: str, data: dict):
            await self.push_event("sub_agent_message", {
                "flow_id": data.get("flow_id", ""),
                "agent_id": data.get("agent_id", ""),
                "type": event_type.replace("sub_agent_", ""),
                "name": data.get("name", ""),
                "arguments": data.get("arguments", {}),
                "content": data.get("content", ""),
                "title": data.get("title", ""),
            })

        agent.on_text_delta = on_text
        agent.on_tool_start = on_tool_start
        agent.on_tool_end = on_tool_end
        agent.permission_callback = permission_callback
        agent.ask_user_callback = ask_user_callback
        agent.on_event_callback = on_event

        try:
            self.clear_error()
            before_snapshot, before_content, before_binary = take_snapshot(cwd)

            user_text = session.messages[-1].content if session.messages else ""
            await agent.run_stream(user_text, cwd, session=session, add_user_message=False)

            after_snapshot, _after_content, after_binary = take_snapshot(cwd)
            binary_set = before_binary | after_binary
            changed_files = detect_file_changes(
                before_snapshot, after_snapshot,
                cwd=cwd, before_content=before_content, binary_set=binary_set,
            )

            if changed_files["files_changed"] > 0:
                git_hash = _get_git_head_hash(cwd)
                checkpoint_filename = save_checkpoint(
                    cwd, changed_files,
                    os.path.basename(self.session.filepath),
                    git_hash,
                )
                files_list = []
                for rel_path in changed_files.get("modified", {}):
                    files_list.append({"path": rel_path, "status": "modified"})
                for rel_path in changed_files.get("deleted", {}):
                    files_list.append({"path": rel_path, "status": "deleted"})
                for rel_path in changed_files.get("added", []):
                    files_list.append({"path": rel_path, "status": "added"})
                for rel_path in changed_files.get("binary", []):
                    files_list.append({"path": rel_path, "status": "binary"})

                summary_data = {
                    "files_changed": changed_files["files_changed"],
                    "files": files_list,
                }

                diff_msg = DiffSummaryMessage(
                    checkpoint_filename=checkpoint_filename,
                    summary=summary_data,
                )
                await session.add_message(diff_msg)

                self.add_diff_summary(checkpoint_filename, {
                    "checkpoint_filename": checkpoint_filename,
                    "summary": summary_data,
                })

                await self.push_event("message", {
                    "role": "diff_summary",
                    "type": "diff_summary",
                    "checkpoint_filename": checkpoint_filename,
                    "summary": summary_data,
                })

            cleanup_checkpoints(cwd)

            await self.push_event("done", {})
        except asyncio.CancelledError:
            await self.push_event("done", {})
        except Exception:
            tb = traceback.format_exc()
            self.set_error(tb)
            await self.push_event("error", {"message": tb})
        finally:
            agent.on_text_delta = original_on_text
            agent.on_tool_start = original_on_tool_start
            agent.on_tool_end = original_on_tool_end
            agent.permission_callback = original_permission
            agent.ask_user_callback = original_ask_user
            agent.on_event_callback = original_on_event
            save_current(session, self.session.filepath)
            self._running = False
            self._running_task = None

    async def sse_event_generator(self, response_id: str):
        """Async generator that yields SSE-formatted events from the queue."""
        queue = self.get_sse_queue(response_id)
        if queue is None:
            yield f"event: error\ndata: {json.dumps({'message': 'Response stream not found'})}\n\n"
            return

        try:
            while True:
                event, data = await queue.get()
                payload = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                yield payload
                if event == "done" or event == "error":
                    break
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            self.remove_sse_queue(response_id)


state = AppState()
