# 扩展点 / 里程碑 / 决策记录

> 所属项目：[Mira Code 设计文档](README.md)

## 扩展点

| 场景 | 需要改动的层 | 不需要动的层 |
| --- | --- | --- |
| 接入新 LLM 供应商 | `providers/` 新增适配器 + `providers.toml` | 其余全部 |
| 新增工具 | `tools/builtin/` 新 Tool + 注册 | 核心循环、UI |
| 新增技能 | `skills/` 新增 SKILL.md | 其余全部 |
| 新增工作 agent（主/子） | `configs/agents/*.toml` 新增配置（system prompt + skills + mcp + tools） | 核心循环、UI 均不动 |
| 接入 MCP 服务 | `configs/mcp.toml` 新增 server | 核心循环、UI 均不动 |
| 新增 UI（IDE 插件） | 表现层新客户端，复用 `AppClient` | 核心层不变 |
| 新增指标 | `telemetry/metrics.py` 注册新口径 | 核心层仅需补埋点 |

## 里程碑（后续细化）

> 目标：每阶段可运行、可验证；先纵向打通，再横向铺开。

| 阶段 | 范围 | 验收 |
| --- | --- | --- |
| **M0 骨架** | 项目脚手架、配置层（分层加载 + 校验）、Provider 抽象 + pydantic-ai 适配器、Tracer 骨架 | 单测通过；能跑通一次无工具的 LLM 调用并产出事件 |
| **M1 核心循环 + CLI** | AgentRuntime 循环、内建工具（shell/file/grep）、MCP 接入、配置驱动的主 agent、CLI（Textual）+ JSONL 事件落盘 | CLI 可完成"让它改个文件"的任务并落盘事件 |
| **M2 Web 服务** | FastAPI + WS 透传、会话管理（含并发上限）、React 前端、审批通道 | 浏览器内与 CLI 完成同一任务，行为一致 |
| **M3 遥测完备** | SQLite 投影、指标聚合、回放引擎（历史重放）、报告落盘、观测 API + 面板 | 任意会话可回放；面板展示指标图表 |
| **M4 能力铺开** | 配置驱动的子 agent（investigator/proto-tester/reviewer）、任务分派与汇报回填、Skills、本地 provider、多会话并发上限、权限规则细化 | 主 agent 可自动分派子任务；多会话并行可切换；多 agent 任务可观测、可回放 |

## 决策记录与剩余 Open Questions

### 已决策

| # | 问题 | 决策 |
| --- | --- | --- |
| 1 | 框架适配器 | 单一 pydantic-ai 后端，不做多框架切换（BackendAdapter 收敛，未来可换） |
| 2 | 表现层技术 | CLI 用 Textual（TUI）；Web 用 React SPA |
| 3 | 事件脱敏 | 不需要脱敏 |
| 4 | 多会话并发 | 会话级隔离 + 独立线程 worker + 全局 `max_concurrent_sessions` 上限（见 [应用层 · 多会话并发](application-layer.md)） |
| 5 | 回放语义 | 回放 = 历史数据重放，不重新发起 LLM/工具请求 |
| 6 | 成本记账 | 基于服务商 usage 响应记账，不做估算 |
| 7 | 子 agent 汇报回填 | 只回填摘要；完整报告存 `sessions/<session_id>/reports/<task_id>.md`（随 session 生命周期）；主 agent 用通用 `file_read` 按路径读取（不新增专用工具） |
| 8a | MCP 凭据 | 配置明文（初期简化，接口预留 env ref / keyring 升级） |
| 8b | MCP 工具权限 | 与内建工具统一 allow / deny / ask 规则 |
| 8c | MCP 隔离 | 初期信任本地配置的 server，不沙箱 |
| 8d | MCP 连接作用域 | 每个会话独立连接，随会话生命周期创建/释放 |
| 9 | 汇报格式 | 不强制格式，重点是信息充分性（结论 / 发现 / 建议 / 风险） |
| 10 | 配置中心编辑 | 配置中心支持可视化编辑并写回配置文件（TOML），含校验与热重载；作为主页面右侧面板视图（见 #21） |
| 11 | 会话列表形态 | 会话列表放会话工作区侧边栏；顶栏「⋯」更多操作承载搜索/筛选/导出/删除等，不单独成页 |
| 12 | Agent 目录 | 并入配置中心的 Agents tab，不单独成页 |
| 13 | 观测页范围 | 观测/回放页并入主页面右侧面板视图（决策 #22），M3 后深化真实指标源接入、多会话对比 |
| 15 | 会话工作区作为首页 | 打开应用直接进入会话工作区 `/`；未选中会话时主区显示新建会话面板（工作区 + 主 agent + 首条消息） |
| 16 | 会话工作区布局 | 左侧=总体概览（Logo + 新建会话 + 工作区树 + 页脚双导航：会话工作区/配置中心），右侧=当前会话一整块（会话栏 + 悬浮输入栏）；无全局顶栏/搜索按钮；两面板间竖直居中三圆点拖拽条调宽（180–420px）；侧边栏可折叠（‹/›） |
| 17 | 输入栏控件 | 📎 引用文件 + 自动通过（审批层次：自动通过/询问/拒绝，棕）+ 模式（选择 agent，蓝）+ 模型/effort 靠右（effort 橙）+ 圆形图标发送按钮 |
| 18 | 新建会话空态 | 点击「＋ 新建会话」→ 右面板居中空态：Logo + 居中输入框 + 下方工作区选择（参考 Kimi Code） |
| 19 | 工作区树交互 | 会话左缩进+层级引导线；仅选中会话浅阴影；会话行悬停归档按钮（归档不展示）；工作区悬停「＋ / ⋯」（重命名/删除） |
| 20 | 视觉规范 | 图标一律扁平 SVG（不用 emoji）；全局禁文字选中（消息区/输入框可选中）；页脚为「会话工作区 / 配置中心 / 观测」三导航 |
| 21 | 配置中心并入主页 | 配置中心不设独立页面/路由，作为主页面右侧面板第二个视图（`body.settings-mode` 切换视图）；复用同一侧边栏与视觉规范；mockup 合并为单一 `mockups/workspace.html`（v5） |
| 22 | 观测独立页 | 观测为独立页面（`/observe`，`mockups/observe.html`），以事件时间线为核心（会话列表 + 时间线 + span 树），**不含回放功能**；与主页共用侧边栏与视觉规范 |
| 23 | 运行时数据布局 | 所有运行数据（全局配置 / workspace 数据 / session 会话 / telemetry）统一收口 `~/.mira-code/`：全局配置在根目录级 `configs/`（首启从内置播种）；workspace 层在 `workspaces/`，目录名为 `{文件夹名}_{全路径哈希}`；workspace 级数据在其层；session 层在 `<ws>/sessions/`，每个 session 一个文件夹（id = hashcode），事件 JSONL 为 `sessions/<session_id>/session_id.jsonl`，子 agent 完整报告在 `sessions/<session_id>/reports/`；SQLite 在 `<ws>/telemetry/mira.db`；数据根可用 `MIRA_HOME` 重定向（路径计算见 `mira/paths.py`，详见 [directory-structure.md](directory-structure.md)） |
| 24 | LLM 调用迁移到 litellm | LLM 调用统一走 **litellm**（`LiteLLMProvider` 替代直连 HTTP/SSE 的 `OpenAICompatibleProvider`，`MockProvider` 保留）；provider 的 `type` 语义改为 litellm provider 前缀（openai/anthropic/ollama/…）；**供应商 / 模型目录以 models.dev 为数据源**：打包快照 `configs/models-dev.json`（离线/测试默认） + `ModelCatalog` 可刷新缓存（`~/.mira-code/models-dev.json`，`refresh()` 拉 `https://models.dev/api.json`）——可选供应商、每供应商模型、`reasoning`（是否支持思考）均来自该数据；**thinking effort 枚举 models.dev 当前不提供**（实测全为布尔 `reasoning`），对 reasoning 模型用默认阶梯 `["low","medium","high"]` + 按模型族/供应商覆盖表，代码结构兼容未来 `reasoning.effort`（dict）直接消费；`effort` 端到端打通（前端 → REST → runtime → litellm `reasoning_effort`）；`ModelInfo` 新增 `thinking_efforts` |
| 25 | model/effort 为每回复参数 | **model / effort 与每条 AI 回复绑定，session 不持有、不更新**（决策修正）：`send_message` 的 `model` 为必填（`effort` 前端每轮随消息发送，可为 off）；`SendMessageBody.model` 必填；前端每轮读取页面上的 model/effort 发送；移除 `session.model` 同步；**runtime 不持有 model/effort 状态**——从 `agent.model/effort` 读取、`run(model=, effort=)` override 后作为每调用参数传递；`llm.request`/`agent.loop.start` 记录本轮模型与 effort。CLI 每轮传 `model=session.model`（其选定默认）。`session.model` 仅为创建时的展示标签。**子 agent 的 `model`/`effort` 可选**：`AgentConfig.model/effort`；未配置时由 `TaskDispatcher` 继承父 runtime 本轮值（经 `dispatch(model=, effort=)` 参数传入：`sub_model = agent.model or model`、`sub_effort = agent.effort or effort`） |
| 26 | provider 单配置 / 模型串 {provider}/{model} | **每种 provider 只允许一个配置，id 即 type**（决策 #25 扩展）：`ProviderConfig.id == type`，同 type 全局唯一（`mutation._update_providers` 校验：type 重复 / id≠type → 422）；配置中心移除「ID / 显示名」行，type 下拉即身份。**模型以 `{provider}/{model}` 规格串标识**：CLI `-m deepseek/deepseek-chat`（去掉 `--provider`）、网页模型弹窗按 provider 分组、`send_message.model` 即为规格串；**不设会话默认 provider、不存 provider 状态**（`Session` 无 provider 字段、`SessionManager` 无默认 provider、runtime/orchestration 无 provider_id），`split_spec`（收口 `mira/util.py`）拆分并按 provider 路由，缺 provider 抛错；`agent.model`/`default_model` 亦为规格串；`/api/config/models` 每模型附 `provider`+`spec`。mock 配置 id 由 `mock-local` 更名为 `mock`（id 即 type） |
| 27 | 工具超时 / 工具名下划线 | 每个 Tool 可单独配置 `timeout_s`（类属性，0=不限时）：`Tool.invoke(ctx, **args)` 在 `timeout_s>0` 时于独立 daemon 线程运行并限时，超时返回 `ToolResult(ok=False)`（底层异常重抛，由 runtime `_execute_tools` 统一转结果）；shell 默认 `timeout_s=60`（subprocess 同步限时）。**工具名统一为下划线 `x_y`**（LLM provider 不支持 `.`）：`file.read`→`file_read`、`search.grep`→`search_grep`、MCP 工具 `mcp.<server>.<tool>`→`mcp_<server>_<tool>`（`_safe_name` 去掉 `.`）；权限通配由 `shell.*` 改为 `shell_*`（`_matches` 对 `_*` 后缀同时匹配裸名前缀，兼容旧 `.*`） |
| 28 | 新增内建工具（参考 nano_claude） | 移植自 `nano_claude/tools` 并适配 Mira 的 `Tool.run`/`ToolContext.resolve`（去掉异步与 file_read_registry 依赖）：**`glob`**（glob 模式文件查找，按 mtime 倒序）、**`todowrite`**（结构化任务清单，持久化到当前会话目录 `sessions/<session_id>/todos.json`）、**`apply_patch`**（结构化补丁批量增/改/删/重命名文件，update 用 unified diff）、**`web_fetch`**（抓取 URL，HTML→文本用 stdlib HTMLParser，httpx 抓取，补齐既有候选）、**`web_search`**（Exa AI 实时搜索：httpx 直调 Exa MCP 端点 web_search_exa，可选 `EXA_API_KEY`，`timeout_s=30`）；已注册 `with_builtins`、加入前端 `TOOL_CANDIDATES`、main/investigator/proto_tester 默认启用；新增对应单测 |
| 29 | DeepSeek thinking 推理链保留 | DeepSeek 思考模式多轮历史需原样回传 `reasoning_content`（否则 litellm 注入占位符警告并降质）：`StreamChunk`/`ChatMessage` 增加 `reasoning_content` 字段，litellm 捕获 `delta.reasoning_content`，runtime `_llm_call` 累积并随 assistant 消息写入历史，`ChatMessage.to_api()` 原样回传（litellm DeepSeek 转换读取该字段）；`LLM_RESPONSE` 事件记录推理链（观测）；MockProvider 支持 `reasoning` 参数（先输出推理链）供测试验证 |

### 剩余待确认

1. **多会话与审批并发**：多个会话同时等待审批时，审批消息如何路由到对应会话？是否做全局审批队列？
2. **会话切换快照粒度**：切换会话时"当前工作状态"展示到什么粒度（最近 N 条事件，还是结构化进度）？
3. **报告文件保留策略**：`sessions/<session_id>/reports/` 的保留与清理策略。
4. **MCP 连接数估算**：每会话挂多个 server 时，连接总数 = 活跃会话数 × 挂载 server 数，是否需要在 quota 中显式计入？
