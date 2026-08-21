# 表现层（Presentation）

> 所属项目：[Mira Code 设计文档](README.md) ｜ 上游契约：[应用层](application-layer.md)
> 技术决策：#2 —— CLI 用 Textual（TUI），Web 用 React

统一门面 `AppClient`：CLI 与 Web 都通过它创建会话、发送消息、消费事件流，实现"同一套 agent 交互"。

## CLI

- 入口命令：`mira`（单次执行 `mira -p "..."` / 交互式 `mira chat`）。
- 交互：基于 **Textual** 的 TUI（决策 #2），支持多行输入、Ctrl+C 中断当前执行、`/` 斜杠命令（如 `/session`、`/cost`、`/replay`）、多会话面板切换。
- 渲染：Textual 组件——流式 token、工具调用卡片（参数/耗时/结果摘要）、状态栏（会话、模型、token、成本）、运行状态（running/idle/waiting）。
- 复用 `AppClient` 拉取事件流并渲染，不做任何业务逻辑。

## Web

- 页面清单与布局设计：[web-ui.md](web-ui.md)。
- 后端：FastAPI，提供 REST（会话/消息 CRUD、观测查询）+ WebSocket（实时事件流透传）。
- 前端：**React** SPA（决策 #2），重点展示：
  - 会话列表与历史，多会话并行工作、来回切换实时查看（运行状态/最近事件）
  - 消息流 + 流式输出 + 工具调用卡片
  - 审批/确认弹窗（HITL）
  - **观测面板**：会话时间线、指标图表（延迟/Token/成本/错误率）、事件回放
- Web 只是把同一份 `EventStream` 序列化后经 WS 透传，与 CLI 拿到的事件完全同构。

## 设计约束（禁止做的事）

| 表现层 | 禁止 |
| --- | --- |
| CLI / Web | 不得直接调 LLM、不得执行 tool、不得访问遥测存储 |

## 相关

- 统一事件流协议：[应用层 · EventStream](application-layer.md)
- 多会话切换与状态视图：[应用层 · 多会话并发与隔离](application-layer.md)
- 观测面板数据来源：[遥测层 · Observe](telemetry.md)
