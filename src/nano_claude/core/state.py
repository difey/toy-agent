"""Shared in-memory application state and client-facing projections."""

import asyncio
import os
from typing import Any, Callable

from nano_claude.core.agent import Agent
from nano_claude.core.diff_service import (
    RollbackError,
    list_checkpoints_for_session,
    rollback_to_checkpoint,
)
from nano_claude.core.message import UserMessage
from nano_claude.core.projections import build_timeline
from nano_claude.core.session import (
    Session,
    list_sessions,
    resume_or_create_session,
    save_current,
    session_info,
    session_path,
)
from nano_claude.core.workspace import build_workspace_view
from nano_claude.infra.bootstrap import build_agent
from nano_claude.interfaces.web.services.provider_service import (
    ProviderInfo,
    delete_provider,
    list_providers as _list_provider_files,
    save_provider,
)


class InteractionState:
    """Encapsulates pending user interaction state and its public view."""

    def __init__(self):
        self._pending_permission: dict | None = None
        self._pending_question: dict | None = None
        self._next_request_id = 1

    def _request_id(self) -> str:
        request_id = f"req_{self._next_request_id}"
        self._next_request_id += 1
        return request_id

    def begin_permission(
        self,
        future: asyncio.Future,
        *,
        tool: str,
        target: str,
        resolved_path: str,
        cwd: str,
    ) -> dict:
        self._pending_permission = {
            "future": future,
            "request_id": self._request_id(),
            "tool": tool,
            "target": target,
            "resolved_path": resolved_path,
            "cwd": cwd,
        }
        return self._pending_permission

    def clear_permission(self) -> None:
        self._pending_permission = None

    def begin_question(
        self,
        future: asyncio.Future,
        *,
        header: str,
        question: str,
        options: list[dict],
        multiple: bool,
    ) -> dict:
        self._pending_question = {
            "future": future,
            "request_id": self._request_id(),
            "header": header,
            "question": question,
            "options": options,
            "multiple": multiple,
        }
        return self._pending_question

    def clear_question(self) -> None:
        self._pending_question = None

    @property
    def pending_permission(self) -> dict | None:
        return self._pending_permission

    @property
    def pending_question(self) -> dict | None:
        return self._pending_question

    def view(self) -> dict:
        permission_view = None
        question_view = None
        if self._pending_permission is not None:
            permission_view = {
                "request_id": self._pending_permission["request_id"],
                "tool": self._pending_permission["tool"],
                "target": self._pending_permission["target"],
                "resolved_path": self._pending_permission["resolved_path"],
                "cwd": self._pending_permission["cwd"],
            }
        if self._pending_question is not None:
            question_view = {
                "request_id": self._pending_question["request_id"],
                "header": self._pending_question["header"],
                "question": self._pending_question["question"],
                "options": self._pending_question["options"],
                "multiple": self._pending_question["multiple"],
            }
        return {
            "pending_permission": permission_view,
            "pending_question": question_view,
        }


class SessionRuntime:
    """Encapsulates current session lifecycle and derived views."""

    def __init__(
        self,
        cwd_getter: Callable[[], str],
        agent_getter: Callable[[], Agent | None],
    ):
        self._cwd_getter = cwd_getter
        self._agent_getter = agent_getter
        self._session: Session | None = None

    @property
    def session(self) -> Session:
        if self._session is None:
            raise RuntimeError("Session runtime is not initialized")
        return self._session

    def initialize(self) -> None:
        cwd = self._cwd_getter()
        session, session_file = resume_or_create_session(cwd)
        self._session = session
        self._session.filepath = session_file
        self.reload_diff_summaries()

    def _refresh_sessions(self) -> list[str]:
        return list_sessions(self._cwd_getter())

    def _find_session_by_name(self, name: str) -> str | None:
        for f in self._refresh_sessions():
            if os.path.splitext(os.path.basename(f))[0] == name:
                return f
        return None

    def sessions_list(self) -> list[dict]:
        files = self._refresh_sessions()
        current_abs = os.path.abspath(self.session.filepath)
        result = []
        for f in files:
            info = session_info(f)
            info["id"] = info["name"]
            info["is_current"] = os.path.abspath(f) == current_abs
            result.append(info)
        result.sort(
            key=lambda s: s.get("updated_at") or s.get("created_at") or 0,
            reverse=True,
        )
        return result

    def _load_session_to_current(self, filepath: str) -> bool:
        try:
            new_session = Session.load(filepath)
        except Exception:
            return False
        self.session.load_messages_from(new_session)
        self.reload_diff_summaries()
        return True

    def load_session_by_name(self, name: str) -> str | None:
        target = self._find_session_by_name(name)
        if target is None:
            return f"Invalid session: {name}"
        if os.path.abspath(target) == os.path.abspath(self.session.filepath):
            return None
        save_current(self.session, self.session.filepath)
        if not self._load_session_to_current(target):
            return f"Failed to load session: {target}"
        return None

    def _create_fresh_session(self) -> None:
        cwd = self._cwd_getter()
        self.session.clear_messages()
        self.session.filepath = session_path(cwd)
        agent = self._agent_getter()
        if agent:
            self.session._ensure_system_prompt(agent._build_system_prompt(cwd))

    def _resume_or_fresh(self) -> None:
        remaining = self._refresh_sessions()
        if remaining:
            if not self._load_session_to_current(remaining[-1]):
                self._create_fresh_session()
        else:
            self._create_fresh_session()

    def delete_session_by_name(self, name: str) -> str | None:
        target = self._find_session_by_name(name)
        if target is None:
            return f"Invalid session: {name}"
        is_current = os.path.abspath(target) == os.path.abspath(self.session.filepath)
        try:
            os.remove(target)
        except OSError as e:
            return f"Error: {e}"
        if is_current:
            self._resume_or_fresh()
        return None

    def timeline(self) -> list[dict]:
        return build_timeline(self.session.messages)

    def _timeline_index_to_user_message_count(self, message_timeline_index: int) -> int:
        """Count user text messages that appear before a timeline index."""
        timeline = self.timeline()
        user_msg_index = 0
        for i, item in enumerate(timeline):
            if i == message_timeline_index:
                break
            if item.get("role") == "user" and item.get("type") == "text":
                user_msg_index += 1
        return user_msg_index

    def _rollback_cutoff_index(self, message_timeline_index: int) -> int:
        """Return the session-message cutoff that keeps the target user message.

        Timeline items are flattened for clients, while rollback truncation happens
        against the original ``Session.messages`` list. This helper first counts
        how many user messages have been seen up to the selected timeline item,
        then finds the matching user message in ``Session.messages`` and returns
        the index immediately after it so the user prompt is preserved.
        """
        timeline = self.timeline()
        target_user_count = 0
        for i, item in enumerate(timeline):
            if item.get("role") == "user" and item.get("type") == "text":
                target_user_count += 1
            if i == message_timeline_index:
                break

        if target_user_count == 0:
            return len(self.session.messages)

        seen_users = 0
        for i, msg in enumerate(self.session.messages):
            if isinstance(msg, UserMessage) and isinstance(msg.content, str):
                seen_users += 1
                if seen_users == target_user_count:
                    return i + 1

        return len(self.session.messages)

    def fork_session(self, message_timeline_index: int) -> dict:
        cwd = self._cwd_getter()
        save_current(self.session, self.session.filepath)
        user_msg_index = self._timeline_index_to_user_message_count(message_timeline_index)
        forked = self.session.fork(user_msg_index)
        new_path = session_path(cwd)
        forked.save(new_path)
        self.session.load_messages_from(forked)
        self.reload_diff_summaries()
        return self.current_meta()

    def rollback_session(self, message_timeline_index: int) -> dict:
        cwd = self._cwd_getter()
        save_current(self.session, self.session.filepath)
        timeline = self.timeline()
        if message_timeline_index < 0 or message_timeline_index >= len(timeline):
            raise ValueError(f"Invalid message index: {message_timeline_index}")

        target_msg = timeline[message_timeline_index]
        target_ts: float = target_msg.get("timestamp", 0.0)
        if target_ts == 0.0:
            raise ValueError("Target message has no timestamp")

        session_file_basename = os.path.basename(self.session.filepath)
        hash_error = None
        try:
            skipped, errors = rollback_to_checkpoint(
                cwd,
                target_ts,
                session_file_basename,
            )
        except RollbackError as e:
            hash_error = str(e)
            skipped, errors = [], [hash_error]

        self.session.truncate_messages(self._rollback_cutoff_index(message_timeline_index))
        save_current(self.session, self.session.filepath)
        self.reload_diff_summaries()
        info = self.current_meta()
        info["skipped_files"] = skipped
        info["errors"] = errors
        info["rollback_hash_error"] = hash_error is not None
        return info

    def new_session(self) -> None:
        cwd = self._cwd_getter()
        save_current(self.session, self.session.filepath)
        self.session.clear_messages()
        agent = self._agent_getter()
        if agent:
            self.session._ensure_system_prompt(agent._build_system_prompt(cwd))
        self.session.filepath = session_path(cwd)

    def reload_diff_summaries(self) -> None:
        session_basename = os.path.basename(self.session.filepath)
        summaries = list_checkpoints_for_session(self._cwd_getter(), session_basename)
        self.session.set_diff_summaries({s["checkpoint_filename"]: s for s in summaries})

    def add_diff_summary(self, checkpoint_filename: str, summary: dict) -> None:
        self.session.add_diff_summary(checkpoint_filename, summary)

    def diff_summaries(self) -> list[dict]:
        return list(self.session.diff_summaries.values())

    def current_meta(self) -> dict:
        info = session_info(self.session.filepath)
        info["is_current"] = True
        info["id"] = info["name"]
        return info


class WebAppState:
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
        self.providers: dict[str, ProviderInfo] = {}

    @property
    def session(self) -> Session:
        return self.session_runtime.session

    @property
    def _pending_permission(self) -> dict | None:
        return self.interaction.pending_permission

    @property
    def _pending_question(self) -> dict | None:
        return self.interaction.pending_question

    def initialize(self, cwd: str) -> None:
        self.cwd = cwd
        self.agent = build_agent(cwd=self.cwd, mode="build")
        self.session_runtime.initialize()
        self.load_providers()

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

    def load_providers(self) -> None:
        providers_list = _list_provider_files()
        self.providers.clear()
        for p in providers_list:
            self.providers[p.name] = p

    def add_provider(self, info: ProviderInfo) -> None:
        save_provider(info)
        self.providers[info.name] = info

    def remove_provider(self, name: str) -> None:
        delete_provider(name)
        self.providers.pop(name, None)

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


state = WebAppState()
