# 目录结构建议

> 所属项目：[Mira Code 设计文档](README.md) ｜ 分层说明见各层文档

```
mira-code/
├── pyproject.toml
├── docs/                       # 设计文档（本目录）
│   ├── README.md               #   总览 + 架构 + 索引
│   ├── presentation.md         #   表现层
│   ├── application-layer.md    #   应用层
│   ├── core-agent-layer.md     #   Agent 核心层
│   ├── telemetry.md            #   遥测层
│   ├── data-models.md          #   数据模型 / 事件 / 指标
│   ├── flows.md                #   时序图
│   ├── directory-structure.md  #   本文件
│   ├── config-examples.md      #   配置示例
│   └── planning.md             #   扩展点 / 里程碑 / 决策
├── configs/                    # 内置默认配置
│   ├── mira.toml               # 运行时默认
│   ├── providers.toml          # provider 默认
│   ├── mcp.toml                # MCP 服务定义
│   └── agents/                 # 主/子 agent 定义 (main/investigator/...)
├── skills/                     # 内置技能 (SKILL.md)
│   └── ...
├── mira/
│   ├── cli/                    # ── 表现层：CLI
│   │   ├── app.py              #   入口
│   │   ├── app_tui.py          #   Textual 应用
│   │   ├── repl.py             #   交互式 REPL
│   │   └── widgets.py          #   Textual 组件（流式/工具卡片/状态栏）
│   ├── web/                    # ── 表现层：Web
│   │   ├── server.py           #   FastAPI 入口
│   │   ├── ws.py               #   WebSocket 事件透传
│   │   ├── routes.py           #   REST 路由
│   │   └── webui/              #   React 前端（SPA）
│   ├── api/                    # ── 应用层：统一契约
│   │   ├── client.py           #   AppClient 门面
│   │   ├── protocol.py         #   消息/事件模型
│   │   ├── session.py          #   SessionManager（隔离 + 并发上限）
│   │   ├── stream.py           #   EventStream
│   │   ├── approval.py         #   审批/HITL 通道
│   │   └── quota.py            #   全局并发配额/排队
│   ├── core/                   # ── Agent 核心层
│   │   ├── runtime.py          #   AgentRuntime 执行循环
│   │   ├── context.py          #   上下文/token 预算
│   │   ├── orchestration.py    #   多 Agent 协作
│   │   ├── config/             #   ── 配置子层
│   │   │   ├── schemas.py
│   │   │   ├── store.py        #   分层加载
│   │   │   └── loader.py
│   │   ├── providers/          #   ── Provider 子层
│   │   │   ├── base.py         #   LLMProvider 抽象
│   │   │   ├── router.py       #   路由/重试/限流/记账
│   │   │   ├── openai.py
│   │   │   ├── anthropic.py
│   │   │   ├── local.py        #   Ollama/vLLM
│   │   │   └── framework/      #   框架适配器（决策 #1：单一 pydantic-ai）
│   │   │       ├── base.py     #   BackendAdapter
│   │   │       └── pydantic_ai.py
│   │   ├── tools/              #   ── 工具子层
│   │   │   ├── base.py
│   │   │   ├── registry.py
│   │   │   ├── permission.py
│   │   │   └── builtin/        #   shell/file/search/web/git
│   │   ├── mcp/                #   ── MCP 服务层
│   │   │   ├── base.py         #   MCP server 抽象
│   │   │   ├── bridge.py       #   MCP 工具 → Tool 桥接
│   │   │   ├── manager.py      #   连接池/健康检查/重连
│   │   │   └── transports.py   #   stdio / HTTP 传输
│   │   ├── skills/             #   ── 技能子层
│   │   │   ├── base.py
│   │   │   ├── registry.py
│   │   │   └── loader.py
│   │   └── agents/             #   ── 工作 Agent 子层
│   │       ├── base.py         #   BaseAgent（由配置生成）
│   │       ├── registry.py     #   AgentRegistry（配置即注册）
│   │       ├── main.py         #   主 agent 装配（规划/分派/汇总）
│   │       └── dispatch.py     #   TaskDispatcher（TaskSpec 执行）
│   └── telemetry/              # ── 遥测层
│       ├── tracer.py           #   Tracer 接口 + EventLogTracer
│       ├── events.py           #   事件 schema
│       ├── store.py            #   JSONL 落盘
│       ├── reports.py          #   子 agent 报告落盘 (reports/<task_id>.md)
│       ├── metrics.py          #   指标聚合
│       ├── db.py               #   SQLite 投影
│       ├── replay.py           #   回放引擎
│       └── observe.py          #   观测查询 API
└── tests/
    ├── unit/                   # 各子层单测
    ├── integration/            # 端到端 (CLI/Web/核心一致)
    └── replay/                 # 回放一致性测试
```

## 运行时数据布局（~/.mira-code/）

仓库内的 `configs/` 是**内置默认配置（种子源）**；所有**运行数据**（全局配置、各 workspace 的数据、session 会话、telemetry）统一收口到 `~/.mira-code/`（数据根可用 `MIRA_HOME` 环境变量重定向，路径计算统一由 `mira/paths.py` 提供）：

```text
~/.mira-code/
├── configs/                        # 全局配置文件（根目录级）
│   ├── mira.toml / providers.toml / mcp.toml
│   ├── skills/                        # 技能定义（标准 SKILL.md 目录：<id>/SKILL.md）
│   └── agents/*.toml
└── workspaces/                     # workspace 层
    └── <文件夹名>_<全路径哈希>/       #   每个 workspace（如 workspace_123hxs1）
        ├── sessions/               #   session 层
        │   └── <session_hashcode>/  #     每个 session（id = hashcode）
        │       ├── session_id.jsonl #       会话事件日志 / 回放源
        │       └── reports/         #       子 agent 完整报告 <task_id>.md
        └── telemetry/              #   workspace 级遥测
            └── mira.db             #     SQLite 索引 / 指标（P4）
```

- **全局配置文件**在数据根目录顶层 `configs/`：首次运行从内置 `configs/` 播种（`seed_global_config`），此后用户编辑以此为准。
- **配置分层**：内置默认 → 全局（`~/.mira-code/configs/`）→ 可选项目/用户层 → 环境变量覆盖。
- **workspace 层**位于 `~/.mira-code/workspaces/`：目录名为 `{文件夹名}_{全路径哈希}`（如 `/home/user/workspace` → `workspace_123hxs1`），同路径确定、跨机器唯一。
- **session 层**位于 `~/.mira-code/workspaces/<ws>/sessions/`：每个 session 一个文件夹（id = hashcode），事件日志为 `sessions/<session_id>/session_id.jsonl`；子 agent 完整报告在 `sessions/<session_id>/reports/`。
- **workspace 级遥测**（SQLite 索引 / 指标）在 `~/.mira-code/workspaces/<ws>/telemetry/mira.db`。
