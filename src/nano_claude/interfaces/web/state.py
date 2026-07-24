"""Shared in-memory application state for the Web UI server."""

import asyncio
import os

from nano_claude.core.agent import Agent
from nano_claude.core.message import UserMessage
from nano_claude.infra.session import Session, list_sessions, save_current, session_info, session_path

from nano_claude.interfaces.web.serializers import serialize_messages_for_api
from nano_claude.interfaces.web.services.diff_service import (
    list_checkpoints_for_session,
    rollback_to_checkpoint,
    RollbackError,
)


class WebAppState:
    """Shared mutable state for the web UI server."""

    def __init__(self):
        self.agent: Agent | None = None
        self.cwd: str = ""
        self.session: Session | None = None
        self.session_file_ref: list[str] = [""]
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

    # ── session helpers ─────────────────────────────────────────────────

    def _refresh_sessions(self) -> list[str]:
        return list_sessions(self.cwd)

    def _get_current_idx(self) -> int | None:
        files = self._refresh_sessions()
        current_abs = os.path.abspath(self.session_file_ref[0])
        for i, f in enumerate(files):
            if os.path.abspath(f) == current_abs:
                return i + 1  # 1-based
        return None

    def sessions_list(self) -> list[dict]:
        files = self._refresh_sessions()
        current_idx = self._get_current_idx()
        result = []
        for i, f in enumerate(files):
            info = session_info(f)
            info["index"] = i + 1
            info["is_current"] = (i + 1 == current_idx)
            result.append(info)
        return result

    def load_session_by_index(self, index: int) -> str | None:
        """Load a session by 1-based index. Returns error message or None."""
        files = self._refresh_sessions()
        if index < 1 or index > len(files):
            return f"Invalid session number: {index}"
        target = files[index - 1]
        if os.path.abspath(target) == os.path.abspath(self.session_file_ref[0]):
            return None  # already current
        save_current(self.session, self.session_file_ref[0])
        try:
            new_session = Session.load(target)
        except Exception as e:
            return f"Failed to load session: {e}"
        self.session.messages.clear()
        self.session.messages.extend(new_session.messages)
        self.session.title = new_session.title
        self.session_file_ref[0] = target
        return None

    def delete_session_by_index(self, index: int) -> str | None:
        """Delete a session by 1-based index. Returns error message or None."""
        files = self._refresh_sessions()
        if index < 1 or index > len(files):
            return f"Invalid session number: {index}"
        target = files[index - 1]
        if os.path.abspath(target) == os.path.abspath(self.session_file_ref[0]):
            return "Cannot delete current active session."
        try:
            os.remove(target)
            return None
        except OSError as e:
            return f"Error: {e}"

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
        self.session.messages.clear()
        self.session.messages.extend(forked.messages)
        self.session.title = forked.title
        self.session_file_ref[0] = new_path
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

        self.session.messages = self.session.messages[:cutoff_idx]

        # ── 4. Save and return ───────────────────────────────────────
        save_current(self.session, self.session_file_ref[0])
        info = self.current_info()
        info["skipped_files"] = skipped
        info["errors"] = errors
        info["rollback_hash_error"] = hash_error is not None
        return info

    def new_session(self) -> None:
        save_current(self.session, self.session_file_ref[0])
        self.session.messages.clear()
        self.session.title = ""
        self.session_file_ref[0] = session_path(self.cwd)

    def current_info(self) -> dict:
        info = session_info(self.session_file_ref[0])
        info["is_current"] = True
        info["index"] = self._get_current_idx() or 1
        info["messages"] = serialize_messages_for_api(self.session.messages)
        info["mode"] = self.agent.mode if self.agent else "build"
        info["setup_needed"] = self.agent is None
        info["diff_summaries"] = list_checkpoints_for_session(
            self.cwd, os.path.basename(self.session_file_ref[0]),
        )
        return info

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
