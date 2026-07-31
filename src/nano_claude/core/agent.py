import asyncio
import json
import platform
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from nano_claude.core.message import (
    AssistantMessage,
    ReasoningDelta,
    TextDelta,
    ToolCall,
    ToolCallArgDelta,
    ToolCallBegin,
    ToolResult,
    UserMessage
)
from nano_claude.core.prompts import PLAN_MODE_TOOLS, PLAN_SYSTEM_PROMPT, SYSTEM_PROMPT
from nano_claude.core.tool_contracts import AgentCallbacks, ToolContext, ToolExecResult
from nano_claude.core.tool_registry import ToolRegistry
from nano_claude.infra.llm import LLMClient
from nano_claude.infra.setup import save_user_config
from nano_claude.core.session import Session, get_plan_dir, get_session_dir


class Agent:
    def __init__(
        self,
        model: str,
        tools: ToolRegistry,
        api_key: str | None = None,
        base_url: str | None = None,
        callbacks: AgentCallbacks | None = None,
        skill_store: Any | None = None,
        mode: str = "build",
    ):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.provider: str | None = None  # set by web UI when model is selected
        self.llm = LLMClient(model=model, api_key=api_key, base_url=base_url)
        self._full_tools = tools
        self.mode = mode
        self.tools = self._get_mode_tools()
        self.callbacks = callbacks or AgentCallbacks()
        self.skill_store = skill_store

    def reconfigure_llm(self, model: str, api_key: str | None = None, base_url: str | None = None, provider: str | None = None) -> None:
        """Update the model/api_key/base_url, recreate the LLM client, and persist to config."""
        self.model = model
        if api_key is not None:
            self.api_key = api_key
        if base_url is not None:
            self.base_url = base_url
        if provider is not None:
            self.provider = provider
        self.llm = LLMClient(model=self.model, api_key=self.api_key, base_url=self.base_url)
        save_user_config(self.model, self.api_key or "", provider=self.provider or "")

    def _get_mode_tools(self) -> ToolRegistry:
        if self.mode == "plan":
            return self._full_tools.filtered_copy(PLAN_MODE_TOOLS)
        return self._full_tools

    def set_mode(self, mode: str) -> None:
        valid = {"plan", "build"}
        if mode not in valid:
            raise ValueError(f"Invalid mode: {mode}. Must be one of {valid}")
        self.mode = mode
        self.tools = self._get_mode_tools()

    async def _call_with_await(self, fn, *args, **kwargs):
        """Call a callback, awaiting it if it returns a coroutine (async function)."""
        result = fn(*args, **kwargs)
        if asyncio.iscoroutine(result):
            result = await result
        return result

    async def _build_tool_calls(self, stream) -> tuple[str, str | None, list[ToolCall]]:
        accumulated_text: list[str] = []
        accumulated_reasoning: list[str] = []
        tool_call_id: dict[int, str] = {}
        tool_call_name: dict[int, str] = {}
        tool_call_args: dict[int, str] = {}

        async for chunk in stream:
            if isinstance(chunk, TextDelta):
                accumulated_text.append(chunk.text)
                if self.callbacks.on_text_delta:
                    await self._call_with_await(self.callbacks.on_text_delta, chunk.text)
            elif isinstance(chunk, ReasoningDelta):
                accumulated_reasoning.append(chunk.text)
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
        self, tool_calls: list[ToolCall], ctx: ToolContext, sess: Session
    ) -> None:
        for call in tool_calls:
            tool = self.tools.get(call.name)

            if not tool:
                exec_result = ToolExecResult(
                    output=f"Error: unknown tool '{call.name}'",
                    title="unknown tool",
                )
                if self.callbacks.on_tool_end:
                    await self._call_with_await(self.callbacks.on_tool_end, call.name, "unknown tool", "", exec_result.metadata)
            else:
                if self.callbacks.on_tool_start:
                    await self._call_with_await(self.callbacks.on_tool_start, call)
                try:
                    exec_result = await tool.execute(call.arguments, ctx)
                except Exception as e:
                    exec_result = ToolExecResult(
                        output=f"Error: {e}",
                        title="error",
                    )
                    if self.callbacks.on_tool_end:
                        await self._call_with_await(self.callbacks.on_tool_end, call.name, "error", "", exec_result.metadata)
                else:
                    if self.callbacks.on_tool_end:
                        await self._call_with_await(self.callbacks.on_tool_end, call.name, exec_result.title, exec_result.output, exec_result.metadata)

            await sess.add_message(ToolResult(
                tool_call_id=call.id,
                content=exec_result.output,
                tool_name=call.name,
            ))

    def _build_system_prompt(self, cwd: str) -> str:
        year = datetime.now().year
        tools_prompt = self.tools.get_tools_prompt(year=year)
        template = PLAN_SYSTEM_PROMPT if self.mode == "plan" else SYSTEM_PROMPT
        prompt = template.format(
            cwd=cwd,
            session_dir=get_plan_dir(cwd),
            platform=platform.system(),
            date=datetime.now().strftime("%a %b %d %Y"),
            tools=tools_prompt,
        )
        # Append skills section if any skills are available
        if self.skill_store and self.skill_store.count > 0:
            from nano_claude.tools.skill import build_skills_section
            prompt += build_skills_section(self.skill_store.list_all())
        return prompt

    def _get_or_create_session(self, session: Session | None, cwd: str) -> Session:
        system_prompt = self._build_system_prompt(cwd)
        if session is not None:
            if session.summarizer is None:
                session.summarizer = self._summarize
            # Ensure the session always has the latest system prompt as the first message
            session._ensure_system_prompt(system_prompt)
            return session
        return Session(
            system_prompt=system_prompt,
            summarizer=self._summarize,
        )

    async def _summarize(self, prompt: str) -> str:
        messages: list = [UserMessage(content=prompt)]
        response = await self.llm.chat(
            messages=messages,
            tools=[],
        )
        return response.content or ""

    async def run(
        self,
        user_message: str,
        cwd: str,
        session: Session | None = None,
        add_user_message: bool = True,
    ) -> str:
        resolved_cwd = str(Path(cwd).resolve())
        ctx = ToolContext(
            cwd=resolved_cwd,
            session_dir=get_session_dir(resolved_cwd),
            permission_callback=self.callbacks.permission_callback,
            ask_user_callback=self.callbacks.ask_user_callback,
            mode=self.mode,
            parent_agent=self,
            on_event=self.callbacks.on_event_callback,
            skill_store=self.skill_store,
        )
        sess = self._get_or_create_session(session, ctx.cwd)
        if add_user_message:
            await sess.add_user_message(user_message)

        while True:
            print("\n[CHAT] Calling LLM...")
            t0 = time.perf_counter()
            response = await self.llm.chat(
                messages=sess.get_messages_for_llm(),
                tools=self.tools.to_openai_tools(),
            )
            duration = time.perf_counter() - t0
            print(f"[CHAT] LLM response received in {duration:.2f}s")

            text_content = response.content or ""
            tool_calls = response.tool_calls or []

            await sess.add_message(
                AssistantMessage(
                    content=text_content,
                    reasoning_content=response.reasoning_content,
                    tool_calls=tool_calls,
                )
            )

            if not tool_calls:
                print("[CHAT] No tool calls, returning response.")
                return text_content

            if tool_calls:
                print(f"[CHAT] LLM returned {len(tool_calls)} tool call(s)")
                for i, call in enumerate(tool_calls, 1):
                    print(f"       [{i}] {call.name}({list(call.arguments.keys())})")
            await self._execute_tool_calls(tool_calls, ctx, sess)
            print("[CHAT] Tool execution completed, continuing loop.")

    async def _consume_interjections(self, sess: Session) -> bool:
        """在每次 LLM 调用前消费用户插入的额外说明。

        额外说明由调用方（Web UI 的 AppState）通过 ``interjection_source``
        回调提供。这里将每条说明作为新的 user message 插入 session，
        使 LLM 能在下一次调用中看到并纠正自身行为。
        返回是否有额外说明被插入。
        """
        if self.callbacks.interjection_source is None:
            return False
        interjections = self.callbacks.interjection_source()
        inserted = False
        for item in interjections or []:
            message = item.get("message")
            if not message:
                continue
            print(f"[STREAM] Inserting interjection: {message[:80]}")
            await sess.add_user_message(message)
            inserted = True
        return inserted

    async def run_stream(
        self,
        user_message: str,
        cwd: str,
        session: Session | None = None,
        add_user_message: bool = True,
    ) -> None:
        resolved_cwd = str(Path(cwd).resolve())
        ctx = ToolContext(
            cwd=resolved_cwd,
            session_dir=get_session_dir(resolved_cwd),
            permission_callback=self.callbacks.permission_callback,
            ask_user_callback=self.callbacks.ask_user_callback,
            mode=self.mode,
            parent_agent=self,
            on_event=self.callbacks.on_event_callback,
            skill_store=self.skill_store,
        )
        sess = self._get_or_create_session(session, ctx.cwd)
        if add_user_message:
            await sess.add_user_message(user_message)

        while True:
            await self._consume_interjections(sess)
            print("\n[STREAM] Calling LLM with streaming...")
            t0 = time.perf_counter()
            stream = self.llm.chat_stream(
                messages=sess.get_messages_for_llm(),
                tools=self.tools.to_openai_tools(),
            )

            text, reasoning, tool_calls = await self._build_tool_calls(stream)
            duration = time.perf_counter() - t0
            print(f"[STREAM] LLM response received in {duration:.2f}s")

            await sess.add_message(AssistantMessage(
                content=text,
                reasoning_content=reasoning,
                tool_calls=tool_calls,
            ))

            if not tool_calls:
                # 若在本次 LLM 调用期间有新的额外说明到达，消费后再跑一轮以回应它们
                inserted = await self._consume_interjections(sess)
                if inserted:
                    print("[STREAM] Followup arrived during final response, continuing to address it.")
                    continue
                print("[STREAM] No tool calls, returning.")
                return

            if tool_calls:
                print(f"[STREAM] LLM returned {len(tool_calls)} tool call(s)")
                for i, call in enumerate(tool_calls, 1):
                    print(f"        [{i}] {call.name}({list(call.arguments.keys())})")
            await self._execute_tool_calls(tool_calls, ctx, sess)
            print("[STREAM] Tool execution completed, continuing loop.")
