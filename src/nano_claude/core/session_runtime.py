"""Current session lifecycle management and derived views."""

import os
import time
from typing import Callable

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
        # 用户在 AI 回复过程中提交的额外说明，等待 agent 在下一次 LLM 调用前消费。
        self.pending_interjections: list[dict] = []

    @property
    def session(self) -> Session:
        if self._session is None:
            raise RuntimeError("Session runtime is not initialized")
        return self._session

    # ── 额外说明（interjection）────────────────────────────────────────

    def submit_followup(self, response_id: str, message: str, running_response_id: str | None) -> None:
        """暂存一条回复过程中的额外说明。

        仅当 response_id 与当前正在运行的回复匹配时才允许入队，否则抛出
        RuntimeError（调用方转换为 400/409）。
        """
        if not running_response_id or running_response_id != response_id:
            raise RuntimeError("没有正在运行的回复，或 response_id 不匹配")
        self.pending_interjections.append({
            "response_id": response_id,
            "message": message,
            "timestamp": time.time(),
        })

    def pop_pending_interjections(self) -> list[dict]:
        """取出并清空所有暂存的额外说明。"""
        items = self.pending_interjections
        self.pending_interjections = []
        return items

    def interjections_pending(self) -> bool:
        return bool(self.pending_interjections)

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
