"""上下文组装 / token 预算。

把 system prompt + 会话历史 + 可用工具描述组装为 LLM 调用输入。
"""

from __future__ import annotations

from mira.core.agents.base import BaseAgent
from mira.core.providers.base import ChatMessage, ChatRole
from mira.core.skills.registry import SkillRegistry
from mira.core.tools.registry import ToolRegistry
from mira.util import count_tokens


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
