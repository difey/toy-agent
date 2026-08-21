# 关键流程（时序）

> 所属项目：[Mira Code 设计文档](README.md) ｜ 相关：[应用层](application-layer.md)、[Agent 核心层](core-agent-layer.md)、[遥测层](telemetry.md)

## 6.1 一次 agent 运行的端到端时序

```mermaid
---
title: 端到端：用户消息 → Agent 执行 → 遥测 → 回放
---
sequenceDiagram
    participant U as 用户 (CLI/Web)
    participant C as AppClient
    participant S as SessionManager
    participant R as AgentRuntime
    participant P as ProviderRouter
    participant L as LLMProvider (适配器)
    participant T as ToolRegistry
    participant TL as Tracer (遥测)

    U->>C: 发送用户消息
    C->>S: 路由到会话
    S->>R: run(user_msg)
    R->>TL: 事件 user.message / agent.loop.start
    R->>R: 组装 context (system + history + tools)

    loop 执行循环
        R->>P: chat_completion(stream)
        P->>L: 调用 LLM
        L-->>R: stream chunks / tool_calls
        R->>TL: 事件 llm.request / llm.stream_chunk / llm.response

        alt 需要调用工具
            R->>T: 执行 tool
            T-->>R: 结果 / 错误
            R->>TL: 事件 tool.call / tool.result / tool.error
        else 生成最终回复
            R-->>S: 完成
        end
    end

    S->>TL: 事件 agent.loop.end / metric.snapshot
    S-->>C: 事件流 (消息 + 增量 + 指标)
    C-->>U: 渲染输出
```

## 6.2 主 Agent 分派子任务（调查 → 汇报 → 汇总）

```mermaid
---
title: 主 Agent 分派子任务
---
sequenceDiagram
    participant U as 用户
    participant M as 主 Agent (main)
    participant D as TaskDispatcher
    participant I as 子 Agent (investigator)
    participant TL as Tracer (遥测)

    U->>M: "调查 X 的实现状态，并给出实现方案"
    M->>D: dispatch_task(target=investigator, goal=...)
    D->>TL: 事件 task.dispatch
    D->>I: 启动子任务（独立 span）
    I->>I: 装配自身上下文 (system_prompt + skills + mcp + tools)
    I->>I: 执行: 读代码 / git 历史 / 原型测试
    I->>TL: 事件 agent.spawn / tool.* / llm.*（子 agent 独立事件树）
    I-->>D: AgentReport (summary / findings / recommendation)
    D->>TL: 事件 task.complete / agent.report
    D->>D: 完整报告落盘 reports/<task_id>.md
    D-->>M: 回填 summary + 报告路径
    M->>M: 需要细节时 file_read(reports/<task_id>.md)
    M->>M: 汇总决策
    M-->>U: 最终回复（含实现方案）
```

## 6.3 遥测：从采集到回放

```mermaid
---
title: 遥测数据流
---
flowchart LR
    CORE["Agent 核心层"] -->|"注入 Tracer 接口"| TR["Tracer"]
    TR -->|"结构化事件"| EVL[("JSONL 事件日志")]
    TR -->|"指标"| MET["Metrics 聚合器"]
    MET --> DB[("SQLite 指标库")]
    EVL -->|"异步投影"| DB
    EVL -->|"事件序列"| REP["Replay 引擎"]
    REP --> UI["CLI / Web 回放视图"]
    DB --> OBS["Observe 查询 API"]
    OBS --> UI
```
