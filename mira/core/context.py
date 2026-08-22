"""上下文组装 / token 预算。

把 system prompt + 会话历史 + 可用工具描述组装为 LLM 调用输入。
"""

from __future__ import annotations

from mira.core.agents.base import BaseAgent
from mira.core.providers.base import ChatMessage, ChatRole
from mira.core.skills.registry import SkillRegistry
from mira.core.tools.registry import ToolRegistry
from mira.util import count_tokens


def repair_tool_call_integrity(history: list[ChatMessage]) -> list[ChatMessage]:
    """修复历史中「缺少 tool 结果」的悬空 tool_call（DeepSeek 硬性要求，发请求前调用）。

    DeepSeek 要求：每条 assistant 消息的 tool_call 都必须有对应的 tool 结果
    （按 tool_call_id 绑定）；若因故障某次调用没有结果（如 a、b 有结果而 c 缺失），
    DeepSeek 会整体拒绝请求。

    修复**完整记录**：对整段历史中每条含 tool_calls 的 assistant 消息，删除那些
    在整段历史里没有对应 tool 结果（tool_call_id 不匹配）的 tool_call，使请求合法。
    （不能只回溯到上一条用户消息：被中断的上一回合若位于当前用户消息之前，同样可能
    残留悬空 call，DeepSeek 依旧会拒绝。）

    原地修改传入的 history（同时治愈 runtime 持有/恢复的历史）并返回同一列表。
    """
    resolved = {
        m.tool_call_id for m in history if m.role == ChatRole.TOOL and m.tool_call_id
    }
    for m in history:
        if m.role == ChatRole.ASSISTANT and m.tool_calls:
            kept = [c for c in m.tool_calls if c.get("id") in resolved]
            if len(kept) != len(m.tool_calls):
                m.tool_calls = kept or None
    return history


def build_context(
    agent: BaseAgent,
    history: list[ChatMessage],
    tools: ToolRegistry,
    skills: SkillRegistry | None = None,
    *,
    max_tokens: int | None = None,
    tool_names: list[str] | None = None,
) -> tuple[list[ChatMessage], list[dict]]:
    """返回 (messages, tool_specs)。

    - system prompt（含技能指令）置于首位；
    - 历史按 token 预算从新到旧截断（保留系统提示与最近消息）；
    - 工具描述只包含启用且已注册的工具；`tool_names` 覆盖默认的 agent 工具集
      （P3：用于并入 MCP 等额外工具）。
    """
    # 发请求前先修复历史中悬空的 tool_call（DeepSeek 完整性要求）
    history = repair_tool_call_integrity(history)
    system = agent.compose_system_prompt(skills)
    messages: list[ChatMessage] = [ChatMessage(role=ChatRole.SYSTEM, content=system)]

    budget = max_tokens or agent.config.token_budget
    est = count_tokens(system)
    kept: list[ChatMessage] = []
    for msg in reversed(history):
        est += count_tokens(msg.content)
        if est > budget:
            break
        kept.append(msg)
    messages.extend(reversed(kept))

    names = tool_names if tool_names is not None else agent.enabled_tools()
    enabled = tools.enabled(names)
    tool_specs = [t.to_openai_spec() for t in enabled]
    return messages, tool_specs
