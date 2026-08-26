# Agent 核心层（Agent Core）

> 所属项目：[Mira Code 设计文档](README.md) ｜ 上层：[应用层](application-layer.md) ｜ 遥测采集：[遥测层](telemetry.md)

核心层是平台的心脏，由 1 个运行时 + 5 个可插拔子层组成。

## AgentRuntime（执行循环）

自研编排循环，保证对**循环控制权**与**遥测埋点**的完全掌控：

```
组装上下文 → 调 Provider(stream) → 解析输出 → (需要工具? 执行工具 → 回填结果) → 循环 → 结束
```

- 上下文组装（ContextBuilder）：system prompt + 会话历史 + 可用 tools/skills/MCP 描述，含 **token 预算**与上下文压缩策略。
- 面向主 agent 自动装配 `dispatch_task` 工具，使其可按 TaskSpec 分派子任务（见下文「编排模型」）。
- 流式输出统一为 `agent.message` + `llm.stream_chunk` 事件，UI 增量渲染。
- 模型 / 思考强度是**每调用参数**（决策 #25）：runtime **不持有** model/effort 状态——从 `agent.model/effort` 读取，`run(model=, effort=)` override 后按参数传递；子 agent 分派未配置时继承父 runtime 本轮值（`dispatch(model=, effort=)`）。
- 通过 `BackendAdapter` 决定底层"谁来真正跑循环"（决策 #1：单一后端，不做多框架切换）：
  - **pydantic-ai**：用其 Model/Tool 能力，循环由我们驱动（或委托其 Agent.run 并透传事件）；
  - 适配器收敛在 `core/providers/framework/` 内，对上层透明；若未来需替换框架，仅改此适配器。

## Config 配置层

| 配置对象 | 内容 |
| --- | --- |
| `AgentConfig` | 工作 agent 的定义：角色(main/sub)、名称、描述、**可选模型/effort**（未配置时子 agent 继承父 runtime 本轮值，决策 #25）、system prompt、启用的 tools/skills/MCP、温度、max_tokens、token 预算、权限规则、汇报格式(report_schema)、分派策略(dispatch) |
| `ProviderConfig` | LLM 供应商：类型（litellm 前缀）、base_url（可空用默认端点）、API key（明文，决策 #8a；已取消 env 引用）、超时、重试、并发上限；**不持有默认模型**（决策 #25，模型由每回复 / agent 决定）；**每种 provider 只允许一个配置，id 即 type**（决策 #26，模型串 `{provider}/{model}` 的 provider = type，`mutation._update_providers` 校验） |
| `RuntimeConfig` | 会话默认值、遥测开关、审批策略、日志级别、并发上限 `max_concurrent_sessions` |

- **分层加载**：内置默认（`configs/`）→ 项目配置（`mira.toml`）→ 用户配置（`~/.config/mira/`）→ 环境变量/CLI 覆盖。
- 使用 pydantic schema 做运行时校验，错误提前暴露。
- 完整配置示例见 [config-examples.md](config-examples.md)。

## Provider LLM 供应商层（决策 #24：统一走 litellm）

- 抽象接口 `LLMProvider`：`stream_chat(messages, *, model, temperature, max_tokens, tools, effort)` → 流式 `StreamChunk`（末片带 usage / finish_reason / tool_calls）；统一覆盖文本补全、工具调用、流式、结构化输出。
- 适配器：
  - `LiteLLMProvider`（真实供应商默认）：所有调用统一经 **litellm**；`config.type` = litellm provider 前缀（openai / anthropic / ollama / gemini / …），模型名 `{type}/{model}`，`effort` → `reasoning_effort`；
  - `MockProvider`：本地可测 / 无 LLM 环境，保留。
- 模型目录：`ModelCatalog` 读取 **models.dev** 快照（`configs/models-dev.json`，可 `refresh()` 拉 `https://models.dev/api.json` 更新缓存）——可选供应商、每供应商模型、`reasoning`（是否支持 thinking）、`thinking_efforts`（默认阶梯 low/medium/high）。每次启动（创建 `AppClient`）时自动在后台 daemon 子线程 `refresh_async()` 刷新快照并写回 `~/.mira-code/models-dev.json`（离线/失败静默；`MIRA_MODELS_DEV_REFRESH=0` 可关闭）。
- `ProviderRouter`：按 provider id 路由 → provider；负责重试（含退避）、聚合 `available_models`（含 effort 标注）。
- 所有往返都经 Tracer 产出 `llm.*` 事件（含 latency、usage、cost；cost 取自服务商用量响应）。

## Tools 工具层

- 接口 `Tool`：
  - `name`、`description`、`params_schema`（JSON Schema，供 LLM 生成参数）、`timeout_s`（超时秒，0=不限时）、`run(ctx, **args) -> ToolResult`；`invoke(ctx, **args)` 在 `timeout_s>0` 时于 daemon 线程限时执行（超时返回 `ToolResult(ok=False)`）。
  - **工具名统一为下划线 `x_y`**（LLM provider 不支持 `.`，如 `file_read`/`search_grep`；MCP 工具 `mcp_<server>_<tool>`）。
- `ToolRegistry`：注册/查找/枚举，供 AgentRuntime 组装 tools 描述。
- 内建工具（`core/tools/builtin/`）：`shell`、文件读写编辑（`file_read`/`file_write`/`file_edit`）、检索（`search_grep`/`glob`）、`todowrite`（任务清单）、`apply_patch`（补丁）、`web_fetch`（URL 抓取）、`web_search`（Exa AI 实时搜索，可选 `EXA_API_KEY`）、`ask_question`（信息不足时向用户提问：问题 + 可选选项，用户点选或自由作答，答案作为工具结果回填）、`dispatch_task`（子任务分派）。
- **DeepSeek thinking**：assistant 消息携带 `reasoning_content` 推理链，多轮历史原样回传（`ChatMessage.to_api`），避免 litellm 占位符警告与多轮降质（决策 #29）。
- **权限模型**：`allow / deny / ask`，按工具 + 路径规则匹配；`ask` 走 [应用层审批通道](application-layer.md)。
- 执行包装：超时、错误捕获、输出截断、耗时统计 —— 全部产出 `tool.*` 事件。
- **MCP 服务作为外部工具源**：MCP server 暴露的工具桥接为 `Tool`，与内建工具共用注册表/权限/遥测，详见下文「MCP 服务层」。

## MCP 服务层（外部工具接入）

- **MCP 作为外部工具源**：MCP server 暴露的工具自动**桥接为 `Tool`**（name / description / params_schema / run → MCP 调用），与内建工具共用一套注册表、权限模型与遥测。
- 传输：`stdio`（本地进程）与 `HTTP/SSE`（远程服务）。
- 配置在 `configs/mcp.toml`：server 名、命令或 URL、认证方式（决策 #8a：**凭据配置明文**，初期简化；接口预留 env ref / keyring 升级）。
- 连接管理（`mcp/manager.py`）：健康检查、超时、断线重连。
- **连接作用域（决策 #8d）：每个会话独立建立自己的 MCP 连接**，随会话生命周期创建/释放；连接数 = 活跃会话数 × 该会话挂载的 server 数，受 `max_concurrent_sessions` 间接约束。
- 权限（决策 #8b）：MCP 工具与内建工具**统一走 `allow / deny / ask` 权限规则**，可逐工具/路径配置。
- 隔离（决策 #8c）：**初期信任本地配置的 server，不做沙箱**；由权限规则兜底高危能力。
- Agent 通过 `mcp = [...]` 声明可用的 MCP 服务；不同 agent 可挂不同 MCP server。

## Skills 技能层

- `Skill` = 元数据（name、description、依赖的 tools、参数 schema）+ **SKILL.md 指令** + 可选资源文件。
- `SkillRegistry` + `Loader`：按名称/描述加载，注入方式二选一：
  - 指令注入 system prompt（轻量）；
  - 作为工具暴露 `use_skill`（按需加载，控制上下文占用）。
- 兼容现有 SKILL.md frontmatter 规范，便于复用社区技能。

## Agents 工作 Agent 层（配置驱动）

**核心诉求：agent 全部声明式定义 —— 新增一个 agent 只写配置（system prompt + skill + MCP + tools + 权限），不写代码。**

- `BaseAgent`：由 `AgentConfig` 生成的运行时实例。运行时只实现"如何执行配置"（通用循环 + 能力装配），**agent 的"是什么"完全由配置决定**。
- 两个角色（`role` 字段）：
  - `main`：直接面对用户消息的主 agent，负责理解意图、规划、分派子任务并汇总决策；
  - `sub`：被主 agent 分派的子 agent，专精单一职责（调查现状 / 原型验证 / 检索等），执行后以结构化 `AgentReport` 汇报。
- `AgentRegistry`：扫描配置目录（内置 `configs/agents/` + 项目 + 用户级）加载所有 agent 定义，校验后生成实例 —— **配置即注册，无需改代码**。
- `AgentConfig` 关键字段（完整示例见 [config-examples.md](config-examples.md)）：
  - 身份：`id` / `role` / `name` / `description`（description 会注入主 agent 上下文，供其判断何时分派）
  - 行为：`system_prompt` / `model` / `effort`（可选，子 agent 未配置时继承父 runtime 本轮值）/ `temperature` / `max_tokens` / `token_budget`
  - 能力装配：`tools` / `skills` / `mcp`（可用的 MCP 服务）
  - 协作：`report_schema`（可选，仅作提示，格式不强制）/ `dispatch`（auto= 主 agent 可自动分派）
- 内建示例（均为配置，非代码）：
  - `main`：主 agent（规划 + 分派 + 汇总）
  - `investigator`：调查当前实现状态（读代码、git 历史），汇报"现状是什么"
  - `proto-tester`：阅读外部文档 + 编写原型/测试验证可行性，汇报"应如何实现某目标"
  - `researcher`：检索外部信息/文档
  - `reviewer`：只读代码审查，输出结构化结论

## 编排模型：主 Agent 分派子任务

**目标：主 agent 收到用户消息 → 按需分派子任务（调查/原型验证/检索）→ 子 agent 结构化汇报 → 主 agent 汇总给出实现方案。**

- **分派入口**：主 agent 通过内建工具 `dispatch_task(spec)` 触发，参数为 `TaskSpec`（见 [数据模型](data-models.md)）；也支持用户显式指定"用 investigator 调查 X"。
- **TaskSpec（分派契约）**：
  - `task_id` / `target_agent`：目标子 agent id
  - `goal`：任务目标（自然语言）
  - `instructions`：附加约束/指令
  - `context`：相关上下文引用（文件路径、文档 URL、上一轮中间结论）
  - `input_payload`：结构化输入
  - `report_schema`：期望汇报格式
  - `expected_output`：验收标准（如"给出实现方案 + 原型测试结果"）
- **执行模型**：
  - 每次分派 = 一次独立子 agent 运行（独立 span，parent = 主 agent 当前 span），**上下文完全隔离**，不污染主 agent 上下文；
  - 子 agent 按自身配置装配 system prompt / skills / MCP / tools 后执行；
  - 子 agent 的 `model` / `effort` **可选**（决策 #25）：配置了则用自己的，未配置则继承父 runtime 本轮值（经 `dispatch(model=, effort=)` 参数传入）；
  - 支持串行与并行分派（并行任务并发执行后聚合）。
- **AgentReport（汇报契约）**：
  - 字段：`summary`（结论摘要）/ `findings`（调查与测试发现）/ `recommendation`（建议的实现方式）/ `artifacts`（产物引用）/ `risks`（风险与待确认点）/ `status`（succeeded/failed）
  - **格式不做强制限制（决策 #9）**：不强制 JSON 或固定节标题，重点是**信息充分性**——至少覆盖结论、发现、建议实现方式、风险/待确认点。
- **回填策略（决策 #7）**：
  - **只回填 `summary`（摘要）到主 agent 上下文**，节省主 agent token 预算；
  - **完整报告落盘到该 session 的报告目录**（`sessions/<session_id>/reports/<task_id>.md`），并在回填时告知主 agent **报告文件路径**；
  - 主 agent 需要细节时，用**通用 `file_read` 工具**按路径读取完整报告（不新增专用工具）。
- **可观测**：主/子 agent 的 span 构成一棵分派树，观测面板可按树查看每次分派的输入、过程与汇报（见 [遥测层](telemetry.md)）。

## 设计约束（禁止做的事）

| Agent 核心层 | 禁止 |
| --- | --- |
| 运行时 / 各子层 | 不得依赖具体 UI 或具体存储实现 |

## 相关

- 数据模型（TaskSpec / AgentReport / 事件）：[data-models.md](data-models.md)
- 分派时序：[flows.md · 6.2](flows.md)
- 会话隔离与并发上限：[application-layer.md](application-layer.md)
- 配置驱动示例：[config-examples.md](config-examples.md)
