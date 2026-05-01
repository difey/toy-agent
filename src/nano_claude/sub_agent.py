import asyncio
import json
import os
import textwrap
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable, Literal

from nano_claude.agent import SYSTEM_PROMPT
from nano_claude.llm import LLMClient
from nano_claude.message import (
    AssistantMessage,
    ReasoningDelta,
    StreamChunk,
    TextDelta,
    ToolCall,
    ToolCallBegin,
    ToolCallArgDelta,
    ToolResult,
    UserMessage,
)
from nano_claude.session import Session
from nano_claude.tool import ToolContext, ToolExecResult, ToolRegistry


@dataclass
class SubAgentConfig:
    id: str
    instruction: str
    scope: list[str] | None = None
    tools: list[str] | None = None
    cwd: str | None = None
    max_turns: int = 10


@dataclass
class SubAgentResult:
    id: str
    status: Literal["success", "error", "timeout"]
    summary: str
    output: str
    files_changed: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class SubAgentCallbacks:
    """Callbacks for real-time sub-agent event streaming to the frontend."""
    on_start: Callable[[str], Awaitable[None]] | None = None
    on_reasoning: Callable[[str, str], Awaitable[None]] | None = None
    on_tool_start: Callable[[str, str, dict], Awaitable[None]] | None = None
    on_tool_end: Callable[[str, str, str, str], Awaitable[None]] | None = None
    on_assistant_text: Callable[[str, str], Awaitable[None]] | None = None
    on_end: Callable[[str, str], Awaitable[None]] | None = None
    on_error: Callable[[str, str], Awaitable[None]] | None = None


class SubAgent:
    """A sub-agent that runs independently with its own LLM, session, and tool registry."""

    def __init__(
        self,
        config: SubAgentConfig,
        model: str,
        api_key: str | None,
        base_url: str | None,
        full_tools: ToolRegistry,
        parent_cwd: str,
        permission_callback=None,
        ask_user_callback=None,
        callbacks: SubAgentCallbacks | None = None,
        mode: str = "build",
    ):
        self.config = config
        self._mode = mode
        self._cwd = str(Path(config.cwd or parent_cwd).resolve())
        self.llm = LLMClient(model=model, api_key=api_key, base_url=base_url)
        self.tools = _filter_tools(full_tools, config.tools)
        self._permission_callback = permission_callback
        self._ask_user_callback = ask_user_callback
        self._callbacks = callbacks

        system_prompt = self._build_system_prompt(self._cwd)
        self.session = Session(system_prompt=system_prompt)

    def _build_system_prompt(self, cwd: str) -> str:
        year = datetime.now().year
        tools_prompt = self.tools.get_tools_prompt(year=year)
        scope_text = ""
        if self.config.scope:
            scope_items = "\n".join(f"  - {s}" for s in self.config.scope)
            scope_text = f"\n## Your Scope\nYou should focus on these files/directories:\n{scope_items}"

        sub_prompt = textwrap.dedent(f"""\
        You are a sub-agent of nanoClaude, working on a specific sub-task delegated by the main agent.

        ## Working Environment
        - Working directory (cwd): {cwd}
        - Platform: {os.name}
        - Today: {datetime.now().strftime("%a %b %d %Y")}

        {tools_prompt}

        ## Your Task
        {self.config.instruction}
        {scope_text}

        ## Rules
        - Focus ONLY on your assigned task. Do not do work outside your scope.
        - When done, provide a clear summary of what you accomplished.
        - You return results to the main agent, not to the user directly.
        - Be concise and efficient.

        ## ⚠️ CRITICAL: Path Usage Rules
        - Your cwd is ALWAYS `{cwd}`.
        - When accessing files, ALWAYS use absolute paths rooted at `{cwd}`.
        """)
        return sub_prompt

    async def run(self) -> SubAgentResult:
        ctx = ToolContext(
            cwd=self._cwd,
            permission_callback=self._permission_callback,
            ask_user_callback=self._ask_user_callback,
            mode=self._mode,
        )
        sess = self.session

        agent_id = self.config.id
        if self._callbacks and self._callbacks.on_start:
            await self._callbacks.on_start(agent_id)

        await sess.add_user_message(self.config.instruction)
        turns = 0

        try:
            while turns < self.config.max_turns:
                turns += 1
                stream = self.llm.chat_stream(
                    messages=sess.messages,
                    tools=self.tools.to_openai_tools(),
                )

                text, reasoning, tool_calls = await self._build_tool_calls_stream(stream, agent_id)

                await sess.add_message(AssistantMessage(
                    content=text,
                    reasoning_content=reasoning,
                    tool_calls=tool_calls,
                ))

                if not tool_calls:
                    if self._callbacks and self._callbacks.on_end:
                        await self._callbacks.on_end(agent_id, text or "")
                    return SubAgentResult(
                        id=agent_id,
                        status="success",
                        summary=_extract_summary(text) or "Task completed.",
                        output=text,
                        files_changed=_find_files_in_session(sess),
                    )

                await self._execute_tool_calls(tool_calls, ctx, sess, agent_id)

            # Max turns reached
            if self._callbacks and self._callbacks.on_end:
                await self._callbacks.on_end(agent_id, text if text else "Reached maximum turns.")
            return SubAgentResult(
                id=agent_id,
                status="timeout",
                summary="Reached maximum turns.",
                output=text if text else "No output before timeout.",
                files_changed=_find_files_in_session(sess),
            )

        except asyncio.TimeoutError:
            if self._callbacks and self._callbacks.on_error:
                await self._callbacks.on_error(agent_id, "Sub-agent timed out.")
            return SubAgentResult(
                id=agent_id,
                status="timeout",
                summary="Sub-agent timed out.",
                output="",
                error="TimeoutError",
            )
        except Exception as e:
            if self._callbacks and self._callbacks.on_error:
                await self._callbacks.on_error(agent_id, str(e))
            return SubAgentResult(
                id=agent_id,
                status="error",
                summary=f"Sub-agent failed: {e}",
                output="",
                error=str(e),
            )

    async def _build_tool_calls_stream(
        self, stream, agent_id: str
    ) -> tuple[str, str | None, list]:
        accumulated_text: list[str] = []
        accumulated_reasoning: list[str] = []
        tool_call_id: dict[int, str] = {}
        tool_call_name: dict[int, str] = {}
        tool_call_args: dict[int, str] = {}

        cb = self._callbacks

        async for chunk in stream:
            if isinstance(chunk, TextDelta):
                accumulated_text.append(chunk.text)
                if cb and cb.on_assistant_text:
                    await cb.on_assistant_text(agent_id, chunk.text)
            elif isinstance(chunk, ReasoningDelta):
                accumulated_reasoning.append(chunk.text)
                if cb and cb.on_reasoning:
                    await cb.on_reasoning(agent_id, chunk.text)
            elif isinstance(chunk, ToolCallBegin):
                tool_call_id[chunk.index] = chunk.id
                tool_call_name[chunk.index] = chunk.name
                tool_call_args.setdefault(chunk.index, "")
            elif isinstance(chunk, ToolCallArgDelta):
                tool_call_args[chunk.index] = tool_call_args.get(chunk.index, "") + chunk.arguments

        text = "".join(accumulated_text)
        reasoning = "".join(accumulated_reasoning)
        calls = [
            ToolCall(
                id=tool_call_id[idx],
                name=tool_call_name[idx],
                arguments=json.loads(tool_call_args[idx] or "{}"),
            )
            for idx in sorted(tool_call_id)
        ]
        return text, reasoning, calls

    async def _execute_tool_calls(
        self, tool_calls: list[ToolCall], ctx: ToolContext, sess: Session,
        agent_id: str | None = None,
    ) -> None:
        cb = self._callbacks
        aid = agent_id or self.config.id
        for call in tool_calls:
            if cb and cb.on_tool_start:
                await cb.on_tool_start(aid, call.name, call.arguments)

            tool = self.tools.get(call.name)
            if not tool:
                exec_result = ToolExecResult(
                    output=f"Error: unknown tool '{call.name}'",
                    title="unknown tool",
                )
                if cb and cb.on_tool_end:
                    await cb.on_tool_end(aid, call.name, "unknown tool", exec_result.output)
            else:
                try:
                    if cb and cb.on_tool_start:
                        pass  # already called above
                    exec_result = await tool.execute(call.arguments, ctx)
                except Exception as e:
                    exec_result = ToolExecResult(
                        output=f"Error: {e}",
                        title="error",
                    )
                    if cb and cb.on_tool_end:
                        await cb.on_tool_end(aid, call.name, "error", exec_result.output)
                else:
                    if cb and cb.on_tool_end:
                        await cb.on_tool_end(aid, call.name, exec_result.title, exec_result.output)

            sess.messages.append(ToolResult(
                tool_call_id=call.id,
                content=exec_result.output,
                tool_name=call.name,
            ))

        await sess._compact()


class SubAgentManager:
    """Manages the lifecycle of multiple sub-agents."""

    def __init__(
        self,
        model: str,
        api_key: str | None,
        base_url: str | None,
        full_tools: ToolRegistry,
        permission_callback=None,
        ask_user_callback=None,
        callbacks: SubAgentCallbacks | None = None,
        mode: str = "build",
    ):
        self._model = model
        self._api_key = api_key
        self._base_url = base_url
        self._full_tools = full_tools
        self._permission_callback = permission_callback
        self._ask_user_callback = ask_user_callback
        self._callbacks = callbacks
        self._mode = mode

    async def run_parallel(
        self,
        configs: list[SubAgentConfig],
        parent_cwd: str,
        callbacks: SubAgentCallbacks | None = None,
    ) -> list[SubAgentResult]:
        effective_callbacks = callbacks or self._callbacks
        sub_agents = [
            SubAgent(
                config=cfg,
                model=self._model,
                api_key=self._api_key,
                base_url=self._base_url,
                full_tools=self._full_tools,
                parent_cwd=parent_cwd,
                permission_callback=self._permission_callback,
                ask_user_callback=self._ask_user_callback,
                callbacks=effective_callbacks,
                mode=self._mode,
            )
            for cfg in configs
        ]

        coros = [sa.run() for sa in sub_agents]
        results = await asyncio.gather(*coros, return_exceptions=True)

        final_results: list[SubAgentResult] = []
        for i, result in enumerate(results):
            cfg = configs[i]
            if isinstance(result, Exception):
                final_results.append(SubAgentResult(
                    id=cfg.id,
                    status="error",
                    summary=f"Unexpected error: {result}",
                    output="",
                    error=str(result),
                ))
            else:
                final_results.append(result)

        return final_results


def _filter_tools(full_tools: ToolRegistry, tool_names: list[str] | None) -> ToolRegistry:
    """Filter the full tool registry to only include specified tool names."""
    if tool_names is None:
        return full_tools
    return full_tools.filtered_copy(set(tool_names))


def _extract_summary(text: str) -> str:
    """Extract a short summary from the agent's final response."""
    if not text:
        return ""
    lines = text.strip().split("\n")
    # Take the first non-empty line as summary
    for line in lines:
        line = line.strip()
        if line and len(line) > 10:
            return line[:200]
    return text[:200]


def _find_files_in_session(sess: Session) -> list[str]:
    """Find files mentioned in tool results (write/edit operations)."""
    files = set()
    for msg in sess.messages:
        if isinstance(msg, ToolResult):
            if msg.tool_name in ("write", "edit", "apply_patch"):
                # Tool name and content hint at the file
                pass
    return list(files)
