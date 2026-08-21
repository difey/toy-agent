"""~/.mira-code/ 数据布局（唯一真相源）。

所有运行数据统一收口到 ~/.mira-code/（可用环境变量 MIRA_HOME 重定向，便于测试隔离）：

    ~/.mira-code/
    ├── configs/                        # 全局配置文件（根目录级：mira/providers/mcp/skills.toml + agents/）
    └── workspaces/                     # workspace 层
        └── <文件夹名>_<全路径哈希>/       #   每个 workspace（如 workspace_123hxs1）
            ├── sessions/               #   session 层
            │   └── <session_hashcode>/  #     每个 session（id = hashcode）
            │       ├── session_id.jsonl #       会话事件日志 / 回放源
            │       └── reports/         #       子 agent 完整报告 <task_id>.md
            └── telemetry/              #   workspace 级遥测
                └── mira.db             #     SQLite 索引 / 指标（P4）
"""

from __future__ import annotations

import os
from pathlib import Path

from mira.util import short_hash


def mira_home() -> Path:
    """数据根目录：默认 ~/.mira-code，可用 MIRA_HOME 环境变量重定向。"""
    return Path(os.environ.get("MIRA_HOME", str(Path.home() / ".mira-code")))


def global_config_dir() -> Path:
    """全局配置文件目录（位于数据根目录的顶层）。"""
    return mira_home() / "configs"


def workspaces_dir() -> Path:
    """workspace 层根目录。"""
    return mira_home() / "workspaces"


def workspace_id(workspace: str | Path) -> str:
    """workspace 标识：{文件夹名}_{全路径哈希}；已是该格式时原样返回。"""
    p = Path(workspace)
    if p.is_absolute() or p != Path(p.name):
        resolved = p.resolve()
        return f"{resolved.name}_{short_hash(str(resolved))}"
    return str(p)


def workspace_dir(workspace: str | Path) -> Path:
    """指定 workspace 的数据目录（workspace 级数据所在层）。"""
    return workspaces_dir() / workspace_id(workspace)


def workspace_meta_path(workspace: str | Path) -> Path:
    """workspace 元数据文件（记录原始路径，供 Web 创建会话等）。"""
    return workspace_dir(workspace) / "workspace.json"


def sessions_dir(workspace: str | Path) -> Path:
    """指定 workspace 下 session 层目录。"""
    return workspace_dir(workspace) / "sessions"


def session_dir(workspace: str | Path, session_id: str) -> Path:
    """指定 workspace 下某 session 的数据目录（id = hashcode）。"""
    return sessions_dir(workspace) / session_id


def session_meta_path(workspace: str | Path, session_id: str) -> Path:
    """某 session 的元数据文件（标题等，随 session 生命周期）。"""
    return session_dir(workspace, session_id) / "meta.json"


def session_log_path(workspace: str | Path, session_id: str) -> Path:
    """某 session 的事件日志文件（会话事件 / 回放源）。"""
    return session_dir(workspace, session_id) / "session_id.jsonl"


def session_reports_dir(workspace: str | Path, session_id: str) -> Path:
    """某 session 内子 agent 完整报告目录（决策 #7）。"""
    return session_dir(workspace, session_id) / "reports"


def telemetry_dir(workspace: str | Path) -> Path:
    """指定 workspace 下 workspace 级遥测目录。"""
    return workspace_dir(workspace) / "telemetry"


def sqlite_path(workspace: str | Path) -> Path:
    """SQLite 索引 / 指标库路径。"""
    return telemetry_dir(workspace) / "mira.db"
