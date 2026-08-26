# 核心数据模型与遥测事件

> 所属项目：[Mira Code 设计文档](README.md) ｜ 相关：[Agent 核心层](core-agent-layer.md)、[遥测层](telemetry.md)

## 会话与消息

| 模型 | 关键字段 |
| --- | --- |
| `Session` | `id`、`workspace`、`agent_type`、`provider/model`、`created_at`、`closed_at`、`meta` |
| `Message` | `id`、`session_id`、`role`(user/assistant/system/tool)、`content`、`created_at`、`seq` |
| `ToolCall` | `id`、`message_id`、`name`、`arguments`、`result`、`status`、`duration_ms`、`cost` |
| `SkillUse` | `skill_name`、`mode`(prompt/tool)、`params`、`result_summary` |
| `TaskSpec` | `task_id`、`target_agent`、`goal`、`instructions`、`context`、`input_payload`、`report_schema`、`expected_output` |
| `AgentReport` | `task_id`、`agent_id`、`status`、`summary`、`findings`、`recommendation`、`artifacts`、`risks`、`report_path`（落盘路径） |

## 遥测事件（Event Sourcing）

统一信封：

```json
{
  "event_id": "uuid",
  "ts": "2026-08-11T10:00:00.123Z",
  "session_id": "sess_01",
  "span_id": "sp_7",
  "parent_span_id": "sp_6",
  "seq": 42,
  "type": "tool.call",
  "payload": { "...": "..." }
}
```

**事件类型（taxonomy）：**

| 域 | 事件类型 |
| --- | --- |
| 会话 | `session.created` / `session.closed` / `session.status`（running/idle/waiting/failed） |
| 消息 | `user.message` / `agent.message` / `agent.message.delta` |
| LLM | `llm.request` / `llm.stream_chunk` / `llm.response` |
| 工具 | `tool.call` / `tool.result` / `tool.error` |
| Agent | `agent.loop.start` / `agent.loop.end` / `agent.spawn` / `agent.join` / `agent.report` |
| 任务分派 | `task.dispatch` / `task.start` / `task.complete` / `task.failed` |
| 技能 | `skill.used` |
| 审批 | `approval.requested` / `approval.resolved` |
| 提问 | `question.requested` / `question.answered` |
| 错误 | `error.raised` |
| 指标 | `metric.snapshot`（周期聚合快照） |

> `llm.request` 载荷含 `provider` / `model` / `effort`（决策 #25：model/effort 是每调用参数，事件记录本轮实际值）。

## 指标口径

| 指标 | 类型 | 说明 |
| --- | --- | --- |
| `llm.latency_ms` | histogram | 单次 LLM 往返延迟 |
| `llm.tokens_in/out/total` | counter | token 消耗 |
| `llm.cost_usd` | counter | 基于服务商 usage 响应记账（不估算） |
| `tool.latency_ms` | histogram | 工具执行耗时 |
| `tool.error_rate` | gauge | 工具失败率 |
| `agent.loop_steps` | counter | 单次任务执行步数 |
| `agent.success_rate` | gauge | 会话级成功率（按结束原因） |
| `session.duration_s` | histogram | 会话时长 |

## 相关

- 事件采集与存储：[遥测层](telemetry.md)
- TaskSpec / AgentReport 的生产与消费：[Agent 核心层 · 编排模型](core-agent-layer.md)
