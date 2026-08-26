# 应用层（Application / 统一契约）

> 所属项目：[Mira Code 设计文档](README.md) ｜ 上层：[表现层](presentation.md) ｜ 下层：[Agent 核心层](core-agent-layer.md)

应用层是"接口层"，定义核心层与表现层之间的**稳定协议**，保证两套 UI 与未来新 UI（如 IDE 插件）行为一致。

## 组成

- **Protocol**：`UserMessage`、`AgentMessage`、事件类型枚举、`SessionSpec` 等数据模型（pydantic）。
- **SessionManager**：创建/恢复/关闭会话；一个会话绑定一个工作区与一个工作 agent；会话是执行与遥测的基本单位。
- **EventStream**：核心层产出的结构化事件流（生成器），支持：
  - 订阅/分发（CLI 进程内订阅；Web 经 WS 逐事件透传）
  - 事件缓冲、重连补偿（Web 断线后按 `last_seq` 补发）
- **审批通道（HITL）**：`tool.call` 若命中 `ask` 权限，事件进入 `approval.requested` 待确认状态；CLI/Web 返回 `approval.resolved` 后继续执行。
- **提问通道（HITL）**：agent 在信息不足需要用户确认时调用 `ask_question` 工具（问题 + 可选预设选项），事件进入 `question.requested` 待回答状态；CLI/Web 展示问题与选项（可点选或自由输入），用户作答后 `question.answered` 解除阻塞，答案作为工具结果回填给 LLM（与审批同为阻塞语义）。
- **自动审批（approval.mode=auto）**：`ask` 命中的工具调用不再直接放行，而是交由配置的**决策 agent**（`[approval].auto_agent`，默认 `approver`，见 [config-examples.md](config-examples.md)）评估：输出 `allow`/`deny` 直接生效（记录 `approval.resolved · auto=true`）；输出 `fallback`（无法判断）或决策 agent 不可用时**回退到人工审批**（照常进入 `approval.requested` 阻塞等待）。`auto_agent` 置空则恢复"auto=直接放行"的旧行为。
- **模型选择（每回复参数，决策 #25）**：`send_message` 的 `model` 为**必填**（`effort` 随消息携带，可为 off）；每条 AI 回复绑定其 model/effort，**session 与 runtime 均不持有、不更新**；`session.model` 仅为创建时的展示标签。

## 多会话并发与隔离（决策 #4）

**目标：同一工作区下可同时开多个会话，各自在后台独立工作；用户可在会话间来回切换查看实时状态；后端有全局并发上限，避免资源过载。**

- **会话隔离**：每个会话是一个独立的执行单元，持有**独立**的 session 上下文、agent 循环、工具会话与 MCP 连接，互不共享状态（只共享只读的工作区文件系统）。
- **并发模型**：每个会话在**独立线程（worker）**中运行各自的 agent 循环；CLI/Web 通过 `EventStream` 订阅指定会话，切换会话 = 切换订阅 + 拉取会话快照（最近事件 + 运行状态）。
- **状态视图**：会话运行状态 `running / idle / waiting(审批) / failed`，UI 可随时看到每个会话"正在做什么"（最近事件摘要）。
- **全局并发上限**：`SessionManager` 维护 `max_concurrent_sessions`（见 [Agent 核心层 · Config](core-agent-layer.md) 的 RuntimeConfig，以及 [配置示例 · mira.toml](config-examples.md)），超过上限的新会话进入**排队/拒绝**（可配置），防止过多 agent 同时消耗 CPU/LLM/内存。
- **配额与优雅降级**：达到上限时，等待已有会话结束或由用户显式关闭；可选的每会话 token/速率配额。

## 设计约束（禁止做的事）

| 应用层 | 禁止 |
| --- | --- |
| 统一契约层 | 不得包含 agent 决策逻辑 |

## 相关

- 事件流生产方：[Agent 核心层 · AgentRuntime](core-agent-layer.md)
- 会话状态事件与消息模型：[数据模型](data-models.md)
- 并发上限配置：[配置示例 · mira.toml](config-examples.md)
- 端到端时序：[流程 · 6.1](flows.md)
