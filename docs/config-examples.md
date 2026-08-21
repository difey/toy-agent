# 配置示例（示意）

> 所属项目：[Mira Code 设计文档](README.md) ｜ 配置层说明见 [Agent 核心层 · Config](core-agent-layer.md)

```toml
# configs/mira.toml — 运行时默认配置（内置默认；运行数据存于 ~/.mira-code/）
[telemetry]
enabled = true
log_dir = "sessions"                 # 相对 workspace：~/.mira-code/workspaces/<ws>/sessions
sqlite_path = "telemetry/mira.db"    # 相对 workspace：~/.mira-code/workspaces/<ws>/telemetry/mira.db
metric_interval_s = 5

[approval]
mode = "ask"        # auto | ask | deny
ask_include = ["shell_*", "file_write"]

[session]
default_agent = "main"
default_model = "gpt-4o-mini"
max_concurrent_sessions = 4   # 全局并发上限，超出排队/拒绝
```

```toml
# configs/agents/main.toml — 主 agent（配置即注册，无需写代码）
[[agents]]
id = "main"
role = "main"
name = "主 Agent"
description = "面向用户的编码助手，负责规划、分派子任务并汇总实现方案"
system_prompt = "你是主 Agent：理解用户目标，必要时分派子任务（调查/原型验证），汇总汇报后给出可执行方案。"
model = "gpt-4o"
temperature = 0.2
max_tokens = 8192
token_budget = 120_000
dispatch = "auto"                     # 允许自动分派子任务

[agents.tools]
enabled = ["dispatch_task", "file_read", "file_write", "file_edit", "search_grep", "glob", "apply_patch", "todowrite", "shell"]

[agents.skills]
enabled = ["planning"]

[agents.mcp]
enabled = ["github", "project-docs"]

[agents.permission]
rules = [
  { tool = "shell_*", path = "**", action = "ask" },
  { tool = "file_read", path = "**", action = "allow" },
]
```

```toml
# configs/agents/investigator.toml — 子 agent：调查实现状态
[[agents]]
id = "investigator"
role = "sub"
name = "实现调查员"
description = "调查当前实现状态：阅读代码与 git 历史，汇报现状。当用户需要了解某功能现状时使用。"
system_prompt = "你是实现调查员：只读调查，不修改代码。输出：现状总结、关键代码位置、与目标的差距。"
model = "gpt-4o-mini"
effort = "high"                        # 可选：思考强度；子 agent 未配置时继承父 runtime 本轮值（决策 #25）
token_budget = 60_000
report_schema = "investigation_report"   # 汇报格式（可选提示，不强制）
dispatch = "auto"

[agents.tools]
enabled = ["file_read", "search_grep", "git_log", "git_show", "git_status"]

[agents.skills]
enabled = ["code-exploration"]

[agents.mcp]
enabled = ["github"]
```

```toml
# configs/agents/proto_tester.toml — 子 agent：读文档 + 原型测试，给出实现建议
[[agents]]
id = "proto-tester"
role = "sub"
name = "原型验证员"
description = "阅读外部文档并对目标做原型/测试验证，汇报应如何实现某目标。"
system_prompt = "你是原型验证员：先读外部文档/示例，再写最小原型或测试验证可行性，最后给出实现方案与风险。"
model = "gpt-4o"
token_budget = 100_000
report_schema = "implementation_plan"    # 汇报格式（可选提示，不强制）
dispatch = "auto"

[agents.tools]
enabled = ["file_read", "file_write", "shell", "web_fetch"]

[agents.skills]
enabled = ["test-driven-development"]

[agents.mcp]
enabled = ["project-docs"]
```

> **model / effort 可选（决策 #25）**：agent 的 `model` / `effort` 均为可选。子 agent 若配置了就用自己的；**未配置则继承父 runtime 本轮的值**（`TaskDispatcher` 在分派时解析：`sub_model = agent.model or parent_model`，`sub_effort = agent.effort or parent_effort`）。

```toml
# configs/mcp.toml — MCP 服务定义
[[mcp.servers]]
id = "github"
transport = "http"            # stdio | http
url = "http://localhost:8931/mcp"
auth = "MIRA_GITHUB_MCP_TOKEN"           # 决策 #8a：明文配置（初期简化）

[[mcp.servers]]
id = "project-docs"
transport = "stdio"
command = ["npx", "-y", "@modelcontextprotocol/server-filesystem", "./docs"]
```

```toml
# configs/providers.toml — LLM 供应商（type = litellm provider 前缀，决策 #24；决策 #25：不持有 default_model）
# api_key 为明文（决策 #8a，已取消 env 引用设计）；未配置留空
# 决策 #26：每种 provider 只允许一个配置，id 即 type（模型串 {provider}/{model} 的 provider = type）
# 默认只保留本地可测 mock；真实供应商由用户在配置中心自行添加
[[providers]]
id = "mock"
type = "mock"
```

> 模型目录来自 models.dev（`configs/models-dev.json` 快照，可经 `ModelCatalog.refresh()` 刷新）：可选供应商、每供应商模型、`reasoning`（是否支持 thinking）；`thinking_efforts` 为 reasoning 模型的默认阶梯 `low/medium/high`（models.dev 当前不提供枚举，见决策 #24）。配置新供应商时只需填 api_key：`type`/`base_url`（有则）由 models.dev 自动带出，`base_url` 留空则用 litellm 默认端点。**模型以 `{provider}/{model}` 规格串标识**（如 `deepseek/deepseek-chat`）：CLI 用 `mira -m deepseek/deepseek-chat`，网页模型弹窗按 provider 分组、以该串发送（决策 #26）。
