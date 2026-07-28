"""Shared in-memory application state for the Web UI server."""

import asyncio
import os
from typing import Any

from nano_claude.core.agent import Agent
from nano_claude.core.message import UserMessage
from nano_claude.infra.session import Session, list_sessions, save_current, session_info, session_path
from nano_claude.infra.session_service import resume_or_create_session
from nano_claude.infra.bootstrap import build_agent

from nano_claude.interfaces.web.serializers import serialize_messages_for_api
from nano_claude.interfaces.web.services.diff_service import (
    list_checkpoints_for_session,
    rollback_to_checkpoint,
    RollbackError,
)
from nano_claude.interfaces.web.services.provider_service import (
    ProviderInfo,
    list_providers as _list_provider_files,
    load_provider,
    save_provider,
    delete_provider,
)


class WebAppState:
    """Shared mutable state for the web UI server."""

    def __init__(self):
        self.agent: Agent | None = None
        self.cwd: str = ""
        self.session: Session | None = None
        # Mutable "reference" to current session file path.
        # We intentionally store it as a single-item list so different
        # components can share and update the same container via [0]
        # (plain str rebinding would not propagate across holders).
        self.session_file_ref: list[str] = [""]
        # Diff summaries for current session, keyed by checkpoint_filename
        self.diff_summaries: dict[str, dict] = {}
        # SSE queues: keyed by response_id
        self._sse_queues: dict[str, asyncio.Queue] = {}
        self._running_response_id: str | None = None
        # Running state for cancellation
        self._running: bool = False
        self._running_task: asyncio.Task | None = None
        # Pending permission state (for file access approval)
        self._pending_permission: dict | None = None  # {future, tool, target, resolved_path}
        # Pending question state (for question tool)
        self._pending_question: dict | None = None  # {future, header, question, options, multiple}
        # Multi-provider state
        self.providers: dict[str, ProviderInfo] = {}  # keyed by user-defined name

    def initialize(self, cwd: str) -> None:
        """Web UI 启动时一次性初始化 state。

        只接受外部传入的 cwd，其余（agent、session 等）从磁盘/配置读取。
        """
        self.cwd = cwd
        self.agent = build_agent(cwd=self.cwd, mode="build")
        session, session_file = resume_or_create_session(self.cwd)
        self.session = session
        self.session_file_ref[0] = session_file
        self._reload_diff_summaries()
        self.load_providers()

    # ── session helpers ─────────────────────────────────────────────────

    def _refresh_sessions(self) -> list[str]:
        return list_sessions(self.cwd)

    def _find_session_by_name(self, name: str) -> str | None:
        """查找 session 文件名（不含扩展名）对应的完整路径。"""
        for f in self._refresh_sessions():
            if os.path.splitext(os.path.basename(f))[0] == name:
                return f
        return None

    def sessions_list(self) -> list[dict]:
        files = self._refresh_sessions()
        current_abs = os.path.abspath(self.session_file_ref[0])
        result = []
        for f in files:
            info = session_info(f)
            info["id"] = info["name"]
            info["is_current"] = (os.path.abspath(f) == current_abs)
            result.append(info)
        # 按 updated_at（后备 created_at）降序排列
        result.sort(
            key=lambda s: s.get("updated_at") or s.get("created_at") or 0,
            reverse=True,
        )
        return result

    def _load_session_to_current(self, filepath: str) -> bool:
        """Load a session file into the current state.session.

        Copies messages and title from the loaded session. Returns True on
        success, False on failure (e.g. file corrupt).
        """
        try:
            new_session = Session.load(filepath)
        except Exception:
            return False
        self.session.load_messages_from(new_session)
        self.session_file_ref[0] = filepath
        self._reload_diff_summaries()
        return True

    def load_session_by_name(self, name: str) -> str | None:
        """Load a session by filename (without extension). Returns error message or None."""
        target = self._find_session_by_name(name)
        if target is None:
            return f"Invalid session: {name}"
        if os.path.abspath(target) == os.path.abspath(self.session_file_ref[0]):
            return None  # already current
        save_current(self.session, self.session_file_ref[0])
        if not self._load_session_to_current(target):
            return f"Failed to load session: {target}"
        return None

    def _resume_or_fresh(self) -> None:
        """Switch to the most recent session, or create a fresh one.

        Mirrors the logic of ``resume_or_create_session()`` but operates on
        the existing in-memory ``state.session`` instead of returning a new
        Session object.
        """
        remaining = self._refresh_sessions()
        if remaining:
            if not self._load_session_to_current(remaining[-1]):
                self._create_fresh_session()
        else:
            self._create_fresh_session()

    def delete_session_by_name(self, name: str) -> str | None:
        """Delete a session by filename (without extension).

        If the active session is deleted, automatically switches to the most
        recent remaining session. Returns error message or None.
        """
        target = self._find_session_by_name(name)
        if target is None:
            return f"Invalid session: {name}"
        is_current = os.path.abspath(target) == os.path.abspath(self.session_file_ref[0])

        try:
            os.remove(target)
        except OSError as e:
            return f"Error: {e}"

        if is_current:
            self._resume_or_fresh()

        return None

    def _create_fresh_session(self) -> None:
        """Reset to a fresh empty session."""
        self.session.clear_messages()
        self.session_file_ref[0] = session_path(self.cwd)
        self.diff_summaries.clear()
        if self.agent:
            self.session._ensure_system_prompt(self.agent._build_system_prompt(self.cwd))

    def fork_session(self, message_api_index: int) -> dict:
        """Fork the current session at the given user message index.

        Creates a new session with all messages before the referenced user
        message, saves it to disk, and switches the current session to it.

        Args:
            message_api_index: Zero-based index of the user message in the
                               serialized API message array (as seen by the
                               frontend, which includes expanded tool entries).

        Returns:
            The current_info dict for the new forked session.
        """
        save_current(self.session, self.session_file_ref[0])

        # Convert API message array index to user-text-only index.
        # The API array has tool_start/tool_result entries expanded, so
        # we need to count only user/text messages to get the correct
        # index for Session.fork().
        api_messages = serialize_messages_for_api(self.session.messages)
        user_msg_index = 0
        for i, m in enumerate(api_messages):
            if i == message_api_index:
                break
            if m.get("role") == "user" and m.get("type") == "text":
                user_msg_index += 1

        forked = self.session.fork(user_msg_index)
        new_path = session_path(self.cwd)
        forked.save(new_path)
        self.session.load_messages_from(forked)
        self.session_file_ref[0] = new_path
        # Reload diff summaries for the new fork
        self._reload_diff_summaries()
        return self.current_info()

    def rollback_session(self, message_api_index: int) -> dict:
        """Rollback all changes (files + messages) after the given user message.

        1. Restore files via checkpoint rollback (with git hash check).
        2. Truncate session messages after that message.
        3. Save and return updated current_info.

        Args:
            message_api_index: Zero-based index of the user message in the
                               serialized API message array (same as fork).

        Returns:
            dict with ``current`` (CurrentInfo), ``skipped_files``, and
            ``errors`` keys.
        """
        save_current(self.session, self.session_file_ref[0])

        # ── 1. Find the target user message's timestamp ──────────────
        api_messages = serialize_messages_for_api(self.session.messages)
        if message_api_index < 0 or message_api_index >= len(api_messages):
            raise ValueError(f"Invalid message index: {message_api_index}")

        target_msg = api_messages[message_api_index]
        target_ts: float = target_msg.get("timestamp", 0.0)
        if target_ts == 0.0:
            raise ValueError("Target message has no timestamp")

        # ── 2. Restore files via checkpoint rollback ─────────────────
        session_file_basename = os.path.basename(self.session_file_ref[0])
        hash_error = None
        try:
            skipped, errors = rollback_to_checkpoint(
                self.cwd, target_ts, session_file_basename,
            )
        except RollbackError as e:
            hash_error = str(e)
            skipped, errors = [], [hash_error]

        # ── 3. Truncate session messages after this message ──────────
        user_msg_index = 0
        for i, m in enumerate(api_messages):
            if i == message_api_index:
                break
            if m.get("role") == "user" and m.get("type") == "text":
                user_msg_index += 1

        user_text_count = 0
        cutoff_idx = len(self.session.messages)
        for i, msg in enumerate(self.session.messages):
            if isinstance(msg, UserMessage) and isinstance(msg.content, str):
                if user_text_count == user_msg_index:
                    cutoff_idx = i
                    break
                user_text_count += 1

        self.session.truncate_messages(cutoff_idx)

        # ── 4. Save and reload diff summaries ───────────────────────────
        save_current(self.session, self.session_file_ref[0])
        self._reload_diff_summaries()
        info = self.current_info()
        info["skipped_files"] = skipped
        info["errors"] = errors
        info["rollback_hash_error"] = hash_error is not None
        return info

    def new_session(self) -> None:
        save_current(self.session, self.session_file_ref[0])
        self.session.clear_messages()
        if self.agent:
            self.session._ensure_system_prompt(self.agent._build_system_prompt(self.cwd))
        self.session_file_ref[0] = session_path(self.cwd)
        # Clear diff summaries for the new session
        self.diff_summaries.clear()

    def current_info(self) -> dict:
        info = session_info(self.session_file_ref[0])
        info["is_current"] = True
        info["id"] = info["name"]
        info["messages"] = serialize_messages_for_api(self.session.messages)
        info["mode"] = self.agent.mode if self.agent else "build"
        info["setup_needed"] = self.agent is None
        # Use diff_summaries from state instead of reading from disk
        info["diff_summaries"] = list(self.diff_summaries.values())
        # Active model/provider info
        info["active_model"] = self.agent.model if self.agent else None
        info["active_provider"] = self.agent.provider if self.agent else None
        return info

    def _reload_diff_summaries(self) -> None:
        """Reload diff summaries from disk for the current session."""
        session_basename = os.path.basename(self.session_file_ref[0])
        summaries = list_checkpoints_for_session(self.cwd, session_basename)
        # Build a dict keyed by checkpoint_filename for easy lookup
        self.diff_summaries.clear()
        for summary in summaries:
            self.diff_summaries[summary["checkpoint_filename"]] = summary

    def add_diff_summary(self, checkpoint_filename: str, summary: dict) -> None:
        """Add or update a diff summary for a checkpoint."""
        self.diff_summaries[checkpoint_filename] = summary

    # ── Provider helpers ────────────────────────────────────────────────

    def load_providers(self) -> None:
        """Reload all provider configs from disk into memory."""
        providers_list = _list_provider_files()
        self.providers.clear()
        for p in providers_list:
            self.providers[p.name] = p

    def add_provider(self, info: ProviderInfo) -> None:
        """Add or replace a provider in both memory and disk."""
        save_provider(info)
        self.providers[info.name] = info

    def remove_provider(self, name: str) -> None:
        """Remove a provider from both memory and disk."""
        delete_provider(name)
        self.providers.pop(name, None)

    # ── SSE helpers ─────────────────────────────────────────────────────

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
        """Push an event to the currently running SSE queue."""
        if self._running_response_id:
            q = self._sse_queues.get(self._running_response_id)
            if q:
                await q.put((event, data))


# ── Globally shared state instance ──────────────────────────────────────

state = WebAppState()
