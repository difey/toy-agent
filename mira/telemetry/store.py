"""JSONL 事件存储：append-only 主存储，每 session 一个文件夹。

会话事件日志存放于：~/.mira-code/workspaces/<workspace>/sessions/<session_id>/session_id.jsonl
（见 mira.paths）。本类接收该 sessions 目录作为根。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from mira.telemetry.events import Event


class EventStore:
    """事件落盘与读取（回放源）。

    sessions_root: 对应 ~/.mira-code/workspaces/<workspace>/sessions/。
    每个 session 一个文件夹（id = hashcode），事件日志文件固定为 session_id.jsonl。
    """

    def __init__(self, sessions_root: str | Path) -> None:
        self.sessions_root = Path(sessions_root)

    def session_dir(self, session_id: str) -> Path:
        return self.sessions_root / session_id

    def path_for(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "session_id.jsonl"

    def append(self, event: Event) -> None:
        path = self.path_for(event.session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")

    def read(self, session_id: str) -> Iterator[Event]:
        """按事件序列读取（回放 / 观测用）。"""
        path = self.path_for(session_id)
        if not path.exists():
            return
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield Event.model_validate_json(line)

    def list_sessions(self) -> list[str]:
        if not self.sessions_root.exists():
            return []
        return sorted(p.name for p in self.sessions_root.iterdir() if p.is_dir())

    def count(self, session_id: str) -> int:
        return sum(1 for _ in self.read(session_id))
