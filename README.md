# Mira Code

Python 编写的 **Coding Agent 平台**：同一套 Agent 核心同时驱动 **CLI** 与 **Web** 两种交互界面，Agent / 模型 / 工具 / 技能 / MCP 全部配置驱动、可插拔，内建遥测、多会话并发与审批（HITL）。

> 架构与各层设计详见 [docs/README.md](docs/README.md)（设计文档）；本文档只讲**怎么用**。

## 功能速览

- **双界面**：终端（交互 REPL / 单次执行 / Textual TUI）与浏览器 Web UI，行为一致（同一事件流协议）
- **配置即 Agent**：新增主/子 Agent、工具、技能只需写 TOML 配置，无需写代码
- **多会话并发**：同一工作区可并行开多个会话，带全局并发上限与配额
- **内建遥测**：事件日志（JSONL）+ 指标（SQLite），支持回放与观测
- **默认 mock Provider**：本地可测、无网络依赖，开箱即用

## 环境要求

- Python ≥ 3.12

## 安装

推荐用 `uv` 创建虚拟环境并安装（含测试依赖）：

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

也可以使用系统允许的方式：

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## 快速开始

### CLI

```bash
mira                     # 交互式 REPL（默认 mock provider）
mira tui                 # Textual 界面
mira -p "帮我梳理这个项目"  # 单次执行后退出
mira -q -p "..."         # 单次执行，只输出最终回复
```

指定工作区与模型：

```bash
mira -m deepseek/deepseek-chat -p "..." -w /path/to/ws
# 模型格式：{provider}/{model}；-w 缺省为当前目录
```

REPL 内命令：`/help` 帮助、`/session` 会话信息、`/exit` 退出。

### Web

```bash
python -m mira.web.server             # 默认端口 8000
python -m mira.web.server --port 8300 # 指定端口
```

浏览器打开 <http://127.0.0.1:8000/>。Web 提供：

- **会话工作区**：创建 / 切换多会话、流式输出、停止会话
- **审批中心**：需人工放行的工具调用（如 shell）
- **配置中心**：查看 / 编辑 agent、provider、模型
- **观测与配额**：事件流、遥测、全局并发用量

端口优先级：`--port` > 环境变量 `MIRA_WEB_PORT` > 默认 `8000`。

## 模型与 Provider

默认只有本地可测的 `mock` provider。使用真实 LLM，在配置文件中添加供应商：

```toml
# configs/providers.toml（全局 ~/.mira-code/configs/ 或仓库 configs/）
[[providers]]
id = "deepseek"
type = "deepseek"          # litellm provider 前缀：openai / anthropic / deepseek / ollama / gemini …
api_key = "sk-..."         # 明文；base_url 留空用 litellm 默认端点
```

配置后以 `{provider}/{model}` 指定模型，例如：

```bash
mira -m deepseek/deepseek-chat -p "你好"
```

## 配置

配置**分层覆盖**：内置默认 → 全局 `~/.mira-code/configs/` → 项目 / 用户层 → 环境变量。

> 首次运行会自动把内置默认配置（仓库 `configs/`，可用 `MIRA_CONFIG_DIR` 重定向）播种到 `~/.mira-code/configs/`；之后改全局这份即可。

| 配置文件 | 作用 |
| --- | --- |
| `mira.toml` | 运行时：遥测、审批模式、会话并发上限、默认 agent / 模型 |
| `providers.toml` | LLM 供应商 |
| `agents/*.toml` | 主 / 子 Agent：system prompt、tools、skills、mcp、权限规则 |
| `skills.toml` | 技能定义 |
| `mcp.toml` | MCP 服务（stdio / http） |

### 常用环境变量

| 变量 | 作用 |
| --- | --- |
| `MIRA_HOME` | 数据根目录（默认 `~/.mira-code`） |
| `MIRA_WEB_PORT` | Web 端口 |
| `MIRA_DEFAULT_AGENT` / `MIRA_DEFAULT_MODEL` | 默认 agent / 模型 |
| `MIRA_APPROVAL_MODE` | 审批模式：`auto` / `ask` / `deny` |
| `MIRA_SESSION_MAX_CONCURRENT_SESSIONS` | 全局并发上限 |
| `MIRA_MCP_DISABLED=1` | 关闭真实 MCP 连接（测试 / 无网络环境） |
| `MIRA_CONFIG_DIR` | 内置默认配置目录（种子源） |
| `MIRA_TELEMETRY_ENABLED` | 是否启用遥测 |

### 数据目录

所有运行数据统一收口在 `~/.mira-code/`（`MIRA_HOME` 可重定向）：

```
~/.mira-code/
├── configs/                          # 全局配置
└── workspaces/<工作区>_<哈希>/
    ├── sessions/<会话id>/
    │   ├── session_id.jsonl          # 会话事件日志 / 回放源
    │   └── reports/                  # 子 agent 报告
    └── telemetry/mira.db             # SQLite 索引 / 指标
```

## 测试

```bash
pytest
```

测试自动把 `MIRA_HOME` 重定向到临时目录并禁用 MCP，不影响真实数据。

## 目录结构（简要）

```
mira/
├── api/          # 应用层：AppClient / 会话 / 事件流 / 审批
├── cli/          # 表现层：REPL / Textual TUI
├── web/          # 表现层：FastAPI + WebSocket + Web UI
├── core/
│   ├── agents/   # 工作 Agent 注册表（配置驱动）
│   ├── config/   # 配置加载 / 合并 / 环境覆盖
│   ├── mcp/      # MCP 桥接与传输
│   ├── providers/# LLM 供应商（litellm / mock）
│   ├── skills/   # 技能注册表
│   └── tools/    # 工具注册表与内置工具
└── telemetry/    # 遥测：事件 / 存储 / 回放 / 观测
```
