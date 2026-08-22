"""AppClient：统一门面。CLI 与 Web 都通过它创建会话、发送消息、消费事件流。

表现层只调用本门面，不直接触达核心层/遥测存储。
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from pathlib import Path

from mira.api.protocol import Session
from mira.api.session import SessionManager
from mira.telemetry.events import Event


class AppClient:
    def __init__(self, manager: SessionManager | None = None) -> None:
        self.manager = manager or SessionManager()
        # 每次启动（创建门面）时后台刷新 models.dev 快照写回 mira-code；
        # MIRA_MODELS_DEV_REFRESH=0 可关闭（测试隔离等）。
        if os.environ.get("MIRA_MODELS_DEV_REFRESH", "1") != "0":
            from mira.core.providers.catalog import ModelCatalog

            ModelCatalog().refresh_async()

    def create_session(
        self,
        workspace: str | Path,
        agent_type: str = "main",
        model: str | None = None,
    ) -> Session:
        return self.manager.create_session(
            workspace, agent_type=agent_type, model=model
        )

    def fork_session(self, session_id: str, until_seq: int) -> Session:
        """分叉：以源会话 until_seq 之前的对话为初始上下文创建新会话。"""
        return self.manager.fork_session(session_id, until_seq)

    def send_message(
        self,
        session_id: str,
        text: str,
        *,
        model: str,
        effort: str | None = None,
        attachments: list[str] | None = None,
    ) -> threading.Thread | None:
        return self.manager.send_message(
            session_id, text, model=model, effort=effort, attachments=attachments
        )

    def events(self, session_id: str, start_seq: int = 0) -> Iterator[Event]:
        yield from self.manager.events(session_id).iter_events(start_seq=start_seq)

    def get_session(self, session_id: str) -> Session:
        return self.manager.get(session_id)

    def list_sessions(self) -> list[Session]:
        return self.manager.list_sessions()

    def close_session(self, session_id: str) -> None:
        self.manager.close_session(session_id)

    def stop_message(self, session_id: str) -> None:
        """请求停止当前正在生成的回复。"""
        self.manager.stop_session(session_id)

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
        """AI 回复期间插入新消息：interrupt 立即斧正 / 否则排队串行。"""
        return self.manager.enqueue_message(
            session_id,
            text,
            model=model,
            effort=effort,
            interrupt=interrupt,
            attachments=attachments,
        )

    def resolve_approval(self, session_id: str, request_id: str, decision: str) -> dict:
        """审批决议：allow / deny / always。"""
        return self.manager.resolve_approval(session_id, request_id, decision)

    def pending_approvals(self, session_id: str) -> list[dict]:
        return self.manager.pending_approvals(session_id)

    def quota_usage(self) -> dict:
        return self.manager.quota_usage()

    def available_agents(self) -> list[dict]:
        return self.manager.available_agents()

    def available_providers(self) -> list[dict]:
        return self.manager.available_providers()

    # ── 配置中心（决策 #10）──────────────────────────────────

    def get_config(self) -> dict:
        """读取全部配置分区（供配置中心渲染）。"""
        return self.manager.get_config()

    def update_config(self, section: str, data: dict) -> dict:
        """校验并写回指定配置分区；写回后热重载。"""
        return self.manager.update_config(section, data)

    def get_models(
        self, provider_id: str | None = None, provider_type: str | None = None
    ) -> dict:
        """聚合可用模型（含 thinking 能力）；provider_type=按 litellm 前缀查 models.dev。"""
        return self.manager.get_models(provider_id, provider_type=provider_type)
