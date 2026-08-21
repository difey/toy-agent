# 遥测层（Telemetry）

> 所属项目：[Mira Code 设计文档](README.md) ｜ 采集来源：[Agent 核心层](core-agent-layer.md) ｜ 展示端：[表现层](presentation.md)

遥测是平台级的横向能力，目标：**监控 + 回放 + 观测**。

## Tracer（采集）

- 核心层通过注入的 `Tracer` 接口采集事件；默认实现 `EventLogTracer`。
- 每个事件带 **trace/span 上下文**（`span_id` / `parent_span_id`），一次 agent 运行 = 一棵事件树，可串联。
- 语义分两类：
  - **事件（Events）**：发生了什么（消息、LLM 往返、工具调用、错误、审批）—— 用于回放与审计。
  - **指标（Metrics）**：量化的数字（延迟、tokens、成本、错误率、成功率）—— 用于聚合与图表。

## 存储

> 所有运行数据统一收口到 `~/.mira-code/`，按 workspace 分层（全局配置 / workspace / session 见 [directory-structure.md](directory-structure.md)）；路径计算见 `mira/paths.py`。

| 存储 | 用途 | 说明 |
| --- | --- | --- |
| **JSONL 事件日志** | 主存储 / 回放源 | append-only，每 session 一个文件夹：`~/.mira-code/workspaces/<ws>/sessions/<session_id>/session_id.jsonl`；含完整载荷（消息、工具参数/结果、LLM 往返） |
| **报告文件目录** | 子 agent 完整汇报 | `~/.mira-code/workspaces/<ws>/sessions/<session_id>/reports/<task_id>.md`（随 session 生命周期），主 agent 按路径用 `file_read` 读取（决策 #7） |
| **SQLite** | 索引 / 观测 / 指标 | `~/.mira-code/workspaces/<ws>/telemetry/mira.db`；由事件异步投影：sessions、messages、tool_calls、events、metrics 表 |

## 回放（Replay）

- **定义（决策 #5）：回放 = 将历史事件数据重新拿出来展示**，是纯读操作，**不发起新的 LLM / 工具请求**。
- `ReplayEngine` 从 JSONL 按事件序列重放，产出与实时一致的 UI 输出。
- 能力：完整回放、按步骤（step-through）、跳转快进、只读（不产生副作用）。

## 观测（Observe）

- `Observe` 查询 API + 简易面板：
  - 会话列表与详情、事件时间线
  - 指标图表（LLM 延迟、token 消耗、工具耗时、成本、错误分布）
  - 从面板一键发起回放

## 设计约束（禁止做的事）

| 遥测层 | 禁止 |
| --- | --- |
| 采集 / 存储 / 回放 / 观测 | 不参与 agent 决策 |

## 相关

- 事件 schema 与指标口径：[data-models.md](data-models.md)
- 遥测数据流时序：[flows.md · 6.3](flows.md)
- 存储目录与模块：[directory-structure.md](directory-structure.md)
