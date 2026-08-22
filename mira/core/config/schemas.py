"""配置 schema（pydantic 运行时校验，错误提前暴露）。

字段口径见 docs/config-examples.md 与 docs/core-agent-layer.md。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ── Agent 配置 ──────────────────────────────────────────────

class AgentRole(str, Enum):
    MAIN = "main"
    SUB = "sub"


class PermissionAction(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class PermissionRule(BaseModel):
    """权限规则：工具 glob + 路径 + 动作。"""

    tool: str
    path: str = "**"
    action: PermissionAction = PermissionAction.ASK


class AgentToolsConfig(BaseModel):
    enabled: list[str] = Field(default_factory=list)


class AgentSkillsConfig(BaseModel):
    enabled: list[str] = Field(default_factory=list)


class AgentMcpConfig(BaseModel):
    enabled: list[str] = Field(default_factory=list)


class AgentPermissionConfig(BaseModel):
    rules: list[PermissionRule] = Field(default_factory=list)


class AgentConfig(BaseModel):
    """工作 agent 定义（配置即注册，无需写代码）。"""

    id: str
    role: AgentRole = AgentRole.SUB
    name: str = ""
    description: str = ""
    system_prompt: str = ""
    model: str | None = None
    effort: str | None = None  # 可选：思考强度（low/medium/high）；子 agent 未配置时继承父 runtime 本轮值（决策 #25）
    temperature: float = 0.2
    max_tokens: int | None = None
    token_budget: int = 120_000
    report_schema: str | None = None
    dispatch: str = "off"  # auto= 主 agent 可自动分派 / off
    tools: AgentToolsConfig = Field(default_factory=AgentToolsConfig)
    skills: AgentSkillsConfig = Field(default_factory=AgentSkillsConfig)
    mcp: AgentMcpConfig = Field(default_factory=AgentMcpConfig)
    permission: AgentPermissionConfig = Field(default_factory=AgentPermissionConfig)


# ── Provider 配置 ───────────────────────────────────────────

class ProviderConfig(BaseModel):
    """LLM 供应商定义（决策 #8a：api_key 明文；决策 #25：provider 不持有默认模型）。"""

    id: str
    type: str = "openai"  # litellm provider 前缀（openai/anthropic/ollama/gemini/…）| mock
    base_url: str | None = None  # 留空则用 litellm 内置默认端点
    api_key: str = ""  # 明文密钥（可在配置中心直接填写，随配置落盘）
    timeout_s: float = 120.0
    max_retries: int = 3
    max_concurrency: int = 8


# ── MCP 服务配置 ────────────────────────────────────────────

class MCPTransport(str, Enum):
    STDIO = "stdio"
    HTTP = "http"


class MCPServerConfig(BaseModel):
    """MCP server 定义（决策 #8a：初期凭据配置明文，接口预留 env ref 升级）。"""

    id: str
    transport: MCPTransport = MCPTransport.STDIO
    command: list[str] | None = None  # stdio：可执行命令（含参数）
    url: str | None = None  # http：服务地址
    auth: str | None = None  # env 引用或明文


# ── Skill 配置 ──────────────────────────────────────────────

class SkillConfig(BaseModel):
    """技能全局定义（agent 通过 [agents.skills].enabled 启用）。"""

    id: str
    name: str = ""
    description: str = ""
    prompt: str = ""  # 指令模板（注入 system prompt 或作为 use_skill 内容）
    tools: list[str] = Field(default_factory=list)  # 依赖工具


# ── 运行时配置（mira.toml） ─────────────────────────────────

class TelemetryConfig(BaseModel):
    enabled: bool = True
    # 以下路径相对 workspace 根（~/.mira-code/<workspace>/）：
    log_dir: str = "sessions"  # 会话事件日志目录（session 级数据）
    sqlite_path: str = "telemetry/mira.db"  # SQLite 索引 / 指标（workspace 级遥测）
    metric_interval_s: float = 5.0


class ApprovalMode(str, Enum):
    AUTO = "auto"
    ASK = "ask"
    ALLOW_ALL = "allow_all"
    DENY = "deny"  # 保留兼容（硬性拒绝）


class ApprovalConfig(BaseModel):
    mode: ApprovalMode = ApprovalMode.ASK
    ask_include: list[str] = Field(default_factory=lambda: ["shell_*", "file_write"])
    # 自动审批（mode=auto）时的决策 agent id；空=直接放行，配置但未注册=回退人工审批
    auto_agent: str | None = "approver"


class SessionConfig(BaseModel):
    default_agent: str = "main"
    default_model: str = "mock/mock-model"
    send_key: Literal["enter", "ctrl_enter"] = "enter"  # 发送快捷键：Enter 直接发送 / Ctrl/Cmd+Enter 发送
    max_concurrent_sessions: int = 4
    queue_on_quota: bool = True  # 超并发上限时：排队（true）/ 拒绝（false）


class RuntimeConfig(BaseModel):
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    approval: ApprovalConfig = Field(default_factory=ApprovalConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
