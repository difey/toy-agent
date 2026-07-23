import glob
import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

from nano_claude.core.message import (
    AssistantMessage,
    Message,
    SystemMessage,
    ToolCall,
    ToolResult,
    UserMessage,
)

_MODE_SWITCH_PREFIX = "[Mode changed to"


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def message_tokens(msg: Message) -> int:
    if isinstance(msg, SystemMessage):
        return estimate_tokens(msg.content)
    elif isinstance(msg, UserMessage):
        if isinstance(msg.content, str):
            return estimate_tokens(msg.content)
        return estimate_tokens(json.dumps(msg.content))
    elif isinstance(msg, AssistantMessage):
        n = estimate_tokens(msg.content or "")
        for tc in msg.tool_calls:
            n += estimate_tokens(json.dumps(tc.arguments)) + 4
        return n
    elif isinstance(msg, ToolResult):
        return estimate_tokens(msg.content)
    return 0


Summarizer = Callable[[str], Awaitable[str]]


def _format_message_for_summary(msg: Message) -> str:
    if isinstance(msg, SystemMessage):
        return f"[System]: {msg.content}"
    elif isinstance(msg, UserMessage):
        return f"[User]: {msg.content}"
    elif isinstance(msg, AssistantMessage):
        parts = [f"[Assistant]: {msg.content or ''}"]
        for tc in msg.tool_calls:
            parts.append(f"  [ToolCall] {tc.name}({json.dumps(tc.arguments)})")
        return "\n".join(parts)
    elif isinstance(msg, ToolResult):
        return f"[ToolResult] ({msg.tool_name}): {msg.content[:500]}"
    return ""


class Session:
    def __init__(
        self,
        system_prompt: str = "",
        max_tokens: int = 100_000,
        summarizer: Summarizer | None = None,
        title: str = "",
    ):
        self.max_tokens = max_tokens
        self.summarizer = summarizer
        self.messages: list[Message] = []
        self.title = title
        if system_prompt:
            self.messages.append(SystemMessage(content=system_prompt))

    async def _generate_title(self, content: str) -> str:
        """Generate a concise session title, using AI summarizer when available."""
        if self.summarizer is not None:
            prompt = (
                "Generate a very short title (max 40 chars, in Chinese) for this conversation session "
                "based on the user's first message. Output ONLY the title, no quotes or extra text.\n\n"
                f"User message: {content[:500]}\n\nTitle:"
            )
            import asyncio
            try:
                title = await asyncio.wait_for(self.summarizer(prompt), timeout=15)
                title = title.strip().strip('"').strip("'").strip()
                if title:
                    return title[:40]
            except Exception:
                pass
        # Fallback: take first non-empty line, strip to ~40 chars
        for line in content.split("\n"):
            line = line.strip()
            if line:
                if len(line) > 40:
                    return line[:37] + "..."
                return line
        return content[:40]

    async def add_user_message(self, content: str) -> int:
        """添加用户消息并自动折叠连续的模式切换消息。
        返回被折叠的消息数量。"""
        if not self.title and content.strip():
            self.title = await self._generate_title(content)
        self.messages.append(UserMessage(content=content))
        removed = self._collapse_mode_switches()
        await self._compact()
        return removed

    async def add_message(self, msg: Message) -> int:
        """添加消息并自动折叠连续的模式切换消息。
        返回被折叠的消息数量。"""
        self.messages.append(msg)
        removed = self._collapse_mode_switches()
        await self._compact()
        return removed

    def total_tokens(self) -> int:
        return sum(message_tokens(m) for m in self.messages)

    def _collapse_mode_switches(self) -> int:
        """移除末尾连续的模式切换 UserMessage，仅保留最后一条。
        返回被移除的消息数量。"""
        # 从末尾向前扫描连续的模式切换消息
        mode_switch_indices: list[int] = []
        for i in range(len(self.messages) - 1, -1, -1):
            msg = self.messages[i]
            if (
                isinstance(msg, UserMessage)
                and isinstance(msg.content, str)
                and msg.content.startswith(_MODE_SWITCH_PREFIX)
            ):
                mode_switch_indices.append(i)
            else:
                break

        # 如果找到至少 2 条连续的，移除前面的，保留最后一条
        removed = 0
        if len(mode_switch_indices) >= 2:
            # mode_switch_indices 是逆序的（从末尾到开头）
            # 保留 mode_switch_indices[0]（最后一条），移除其他的
            indices_to_remove = mode_switch_indices[1:]  # 除最后一条外的所有
            for idx in sorted(indices_to_remove, reverse=True):
                self.messages.pop(idx)
            removed = len(indices_to_remove)

        return removed

    async def _compact(self) -> None:
        if self.summarizer is None:
            while self.total_tokens() > self.max_tokens and len(self.messages) > 1:
                if not self._remove_oldest_turn():
                    break
            return

        while self.total_tokens() > self.max_tokens and len(self.messages) > 1:
            if not await self._summarize_oldest_turn():
                break

    async def _summarize_oldest_turn(self) -> bool:
        if self.summarizer is None:
            return self._remove_oldest_turn()

        user_indices = [
            i for i in range(len(self.messages))
            if isinstance(self.messages[i], UserMessage)
        ]
        if len(user_indices) < 2:
            return False

        first = user_indices[0]
        end = user_indices[1] - 1

        turn = self.messages[first:end + 1]
        text = "\n\n".join(_format_message_for_summary(m) for m in turn)
        prompt = (
            "Summarize this conversation turn in 1-3 sentences in English. "
            "Preserve key decisions, code changes, file paths, and tool actions.\n\n"
            f"{text}\n\nSummary:"
        )

        import asyncio
        summary = await asyncio.wait_for(self.summarizer(prompt), timeout=30)

        for _ in range(first, end + 1):
            self.messages.pop(first)

        self.messages.insert(first, SystemMessage(
            content=f"[Conversation summary]: {summary}"
        ))
        return True

    def _remove_oldest_turn(self) -> bool:
        user_indices = [
            i for i in range(len(self.messages))
            if isinstance(self.messages[i], UserMessage)
        ]
        if len(user_indices) < 2:
            return False
        first = user_indices[0]
        end = user_indices[1] - 1
        for _ in range(first, end + 1):
            self.messages.pop(first)
        return True

    def _ensure_system_prompt(self, system_prompt: str) -> None:
        """Ensure the session has the current system prompt as the first message."""
        if not system_prompt:
            return
        # Replace existing SystemMessage at position 0, or insert at front
        if self.messages and isinstance(self.messages[0], SystemMessage):
            self.messages[0].content = system_prompt
        else:
            self.messages.insert(0, SystemMessage(content=system_prompt))

    def save(self, path: str) -> None:
        # Extract system prompt as a separate field
        system_prompt = ""
        for m in self.messages:
            if isinstance(m, SystemMessage):
                system_prompt = m.content
                break

        data = {
            "max_tokens": self.max_tokens,
            "title": self.title,
            "system_prompt": system_prompt,
            "messages": [
                {
                    "type": type(m).__name__,
                    "data": _serialize_message(m),
                }
                for m in self.messages
            ],
        }
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def fork(self, message_api_index: int) -> "Session":
        """Create a new Session containing messages up to (but not including)
        the user message at the given index in the serialized API format.

        The API format (serialize_messages_for_api) skips SystemMessage entries
        and expands tool_calls, so we count only UserMessage (text) entries to
        locate the cut-off point.

        Args:
            message_api_index: The zero-based index of the user text message in
                               the serialized API message array.

        Returns:
            A new Session with the forked message history (system_prompt + all
            messages before the referenced user message). The new session has
            no title — it will be regenerated on the first new user message.
        """
        # Find the cut-off index in self.messages by counting user text messages
        user_text_count = 0
        cutoff = len(self.messages)  # default: include everything
        for i, msg in enumerate(self.messages):
            if isinstance(msg, UserMessage) and isinstance(msg.content, str):
                if user_text_count == message_api_index:
                    cutoff = i  # stop before this message
                    break
                user_text_count += 1

        # Build the forked session
        forked = Session(
            max_tokens=self.max_tokens,
            summarizer=self.summarizer,
            title="",
        )
        forked._ensure_system_prompt(self._get_system_prompt())
        # Copy messages from position 1 (after system prompt) up to cutoff
        forked.messages.extend(self.messages[1:cutoff])
        return forked

    def _get_system_prompt(self) -> str:
        """Return the current system prompt string, or empty string."""
        if self.messages and isinstance(self.messages[0], SystemMessage):
            return self.messages[0].content
        return ""

    @classmethod
    def load(cls, path: str) -> "Session":
        data = json.loads(Path(path).read_text())
        title = data.get("title", "")
        system_prompt = data.get("system_prompt", "")
        session = cls(
            max_tokens=data.get("max_tokens", 100_000),
            title=title,
            system_prompt=system_prompt,
        )
        session.messages = [_deserialize_message(item) for item in data["messages"]]
        return session


def _serialize_message(msg: Message) -> dict:
    if isinstance(msg, SystemMessage):
        return {"content": msg.content}
    elif isinstance(msg, UserMessage):
        return {"content": msg.content}
    elif isinstance(msg, AssistantMessage):
        data: dict = {
            "content": msg.content,
            "tool_calls": [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in msg.tool_calls
            ],
        }
        if msg.reasoning_content is not None:
            data["reasoning_content"] = msg.reasoning_content
        return data
    elif isinstance(msg, ToolResult):
        return {
            "tool_call_id": msg.tool_call_id,
            "content": msg.content,
            "tool_name": msg.tool_name,
        }
    raise TypeError(f"Unknown message type: {type(msg)}")


def _deserialize_message(item: dict) -> Message:
    msg_type = item["type"]
    data = item["data"]
    if msg_type == "SystemMessage":
        return SystemMessage(content=data["content"])
    elif msg_type == "UserMessage":
        return UserMessage(content=data["content"])
    elif msg_type == "AssistantMessage":
        return AssistantMessage(
            content=data.get("content"),
            reasoning_content=data.get("reasoning_content"),
            tool_calls=[
                ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
                for tc in data.get("tool_calls", [])
            ],
        )
    elif msg_type == "ToolResult":
        return ToolResult(
            tool_call_id=data["tool_call_id"],
            content=data["content"],
            tool_name=data.get("tool_name", ""),
        )
    raise TypeError(f"Unknown message type: {msg_type}")


SESSION_DIR = os.path.join(os.path.expanduser("~"), ".nano_claude", "sessions")
INDEX_FILE = os.path.join(SESSION_DIR, "index.json")


def _cwd_hash(cwd: str) -> str:
    return hashlib.sha256(cwd.encode()).hexdigest()[:16]


def _load_index() -> dict[str, str]:
    if os.path.exists(INDEX_FILE):
        try:
            return json.loads(Path(INDEX_FILE).read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_index(index: dict[str, str]) -> None:
    os.makedirs(SESSION_DIR, exist_ok=True)
    Path(INDEX_FILE).write_text(json.dumps(index, indent=2, ensure_ascii=False))


def _ensure_session_dir(cwd: str) -> str:
    """Get or create the session directory for a given cwd.

    Uses an index file (~/.nano_claude/sessions/index.json) to map
    resolved cwd paths to stable hash-based folder names.
    """
    resolved_cwd = str(Path(cwd).resolve())
    index = _load_index()
    if resolved_cwd in index:
        h = index[resolved_cwd]
    else:
        h = _cwd_hash(resolved_cwd)
        index[resolved_cwd] = h
        _save_index(index)
    dir_path = os.path.join(SESSION_DIR, h)
    os.makedirs(dir_path, exist_ok=True)
    return dir_path


def session_path(cwd: str) -> str:
    ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    session_dir = _ensure_session_dir(cwd)
    return os.path.join(session_dir, f"{ts}.json")


def list_sessions(cwd: str) -> list[str]:
    session_dir = _ensure_session_dir(cwd)
    pattern = os.path.join(session_dir, "*.json")
    return sorted(glob.glob(pattern))


def get_session_dir(cwd: str) -> str:
    """Return the session directory path for a given cwd (for plan files, etc.)."""
    return _ensure_session_dir(cwd)


def migrate_old_sessions(cwd: str) -> int:
    """Migrate session files from <cwd>/.session/ to the new home-directory location.

    Returns the number of files migrated.
    """
    old_dir = os.path.join(cwd, ".session")
    if not os.path.isdir(old_dir):
        return 0
    old_files = sorted(glob.glob(os.path.join(old_dir, "*.json")))
    if not old_files:
        return 0
    new_dir = _ensure_session_dir(cwd)
    count = 0
    for f in old_files:
        new_path = os.path.join(new_dir, os.path.basename(f))
        if not os.path.exists(new_path):
            shutil.copy2(f, new_path)
            count += 1
    return count


def session_info(filepath: str) -> dict:
    try:
        sess = Session.load(filepath)
        first_msg = ""
        for m in sess.messages:
            if isinstance(m, UserMessage) and isinstance(m.content, str):
                first_msg = m.content
                break
        title = sess.title or (first_msg[:40] if first_msg else "(empty)")
        return {
            "path": filepath,
            "name": os.path.splitext(os.path.basename(filepath))[0],
            "title": title,
            "messages": len(sess.messages),
            "tokens": sess.total_tokens(),
            "preview": first_msg[:60] + ("..." if len(first_msg) > 60 else ""),
        }
    except Exception:
        return {
            "path": filepath,
            "name": os.path.basename(filepath),
            "title": "(unreadable)",
            "messages": 0,
            "tokens": 0,
            "preview": "(unreadable)",
        }


def save_current(session: "Session", filepath: str) -> None:
    if session.messages:
        session.save(filepath)
