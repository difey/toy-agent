import json
import platform
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Callable

from toy_agent.llm import LLMClient
from toy_agent.message import (
    AssistantMessage,
    ReasoningDelta,
    TextDelta,
    ToolCall,
    ToolCallArgDelta,
    ToolCallBegin,
    ToolResult,
)
from toy_agent.session import Session
from toy_agent.tool import ToolContext, ToolExecResult, ToolRegistry


SYSTEM_PROMPT = textwrap.dedent("""\
You are ToyAgent, a CLI coding assistant. You help users write code by using tools.

## Working Environment
- Working directory: {cwd}
- Platform: {platform}
- Today: {date}

## Available Tools
You have the following tools: bash, read, write, edit, glob, grep, webfetch, websearch, codesearch.
- Use `bash` to run shell commands (install packages, run code, check directories).
- Use `read` to view file contents (with optional offset/limit for large files).
- Use `write` to create or overwrite files.
- Use `edit` to perform precise string replacements in existing files.
- Use `glob` to find files by name pattern (e.g. "**/*.py").
- Use `grep` to search file contents with regex.
- Use `webfetch` to fetch and convert web page content (markdown by default).
- Use `websearch` to search the web for up-to-date information.
- Use `codesearch` to search for code examples, documentation, and API references.

## Tool Usage Guidelines
- ALWAYS prefer `edit` over `write` when modifying existing files.
- ALWAYS use `read` to understand existing code before editing.
- Use `grep` to search code contents, `glob` for filename patterns.
- Use `websearch` for current events, recent docs, or information beyond your knowledge cutoff.
- Use `codesearch` for programming questions, library docs, and API examples.
- Use `webfetch` to read the full content of a specific URL found via websearch.
- Describe each `bash` command in 5-10 words via the `description` parameter.
- Use absolute paths for filePath in the `read`, `write`, and `edit` tools.
- When editing, preserve exact indentation (tabs/spaces) from the original.
- Never generate or assume URLs unless you are confident they are correct.
- When done, summarize what was done in 1-3 sentences.

## Code Conventions
- Follow existing code style in the project.
- Use clear, descriptive variable names.
- Add minimal comments.

## Response Style
- Be concise. Do not explain your reasoning unless asked.
- One word answers when appropriate.
- Output text directly, avoid preambles and postambles.
""")


class Agent:
    def __init__(
        self,
        model: str,
        tools: ToolRegistry,
        api_key: str | None = None,
        base_url: str | None = None,
        on_text_delta: Callable | None = None,
        on_tool_start: Callable | None = None,
        on_tool_end: Callable | None = None,
    ):
        self.llm = LLMClient(model=model, api_key=api_key, base_url=base_url)
        self.tools = tools
        self.on_text_delta = on_text_delta
        self.on_tool_start = on_tool_start
        self.on_tool_end = on_tool_end

    async def _build_tool_calls(self, stream) -> tuple[str, str | None, list[ToolCall]]:
        accumulated_text: list[str] = []
        accumulated_reasoning: list[str] = []
        tool_call_id: dict[int, str] = {}
        tool_call_name: dict[int, str] = {}
        tool_call_args: dict[int, str] = {}

        async for chunk in stream:
            if isinstance(chunk, TextDelta):
                accumulated_text.append(chunk.text)
                if self.on_text_delta:
                    self.on_text_delta(chunk.text)
            elif isinstance(chunk, ReasoningDelta):
                accumulated_reasoning.append(chunk.text)
            elif isinstance(chunk, ToolCallBegin):
                tool_call_id[chunk.index] = chunk.id
                tool_call_name[chunk.index] = chunk.name
                tool_call_args.setdefault(chunk.index, "")
            elif isinstance(chunk, ToolCallArgDelta):
                tool_call_args[chunk.index] = tool_call_args.get(chunk.index, "") + chunk.arguments

        text = "".join(accumulated_text)
        reasoning = "".join(accumulated_reasoning) or None
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
                if self.on_tool_end:
                    self.on_tool_end(call.name, "unknown tool", "")
            else:
                if self.on_tool_start:
                    self.on_tool_start(call)
                try:
                    exec_result = await tool.execute(call.arguments, ctx)
                except Exception as e:
                    exec_result = ToolExecResult(
                        output=f"Error: {e}",
                        title="error",
                    )
                    if self.on_tool_end:
                        self.on_tool_end(call.name, "error", "")
                else:
                    if self.on_tool_end:
                        self.on_tool_end(call.name, exec_result.title, exec_result.output)

            sess.messages.append(ToolResult(
                tool_call_id=call.id,
                content=exec_result.output,
            ))

        await sess._compact()

    def _build_system_prompt(self, cwd: str) -> str:
        return SYSTEM_PROMPT.format(
            cwd=cwd,
            platform=platform.system(),
            date=datetime.now().strftime("%a %b %d %Y"),
        )

    def _get_or_create_session(self, session: Session | None, cwd: str) -> Session:
        if session is not None:
            if session.summarizer is None:
                session.summarizer = self._summarize
            return session
        return Session(
            system_prompt=self._build_system_prompt(cwd),
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
    ) -> str:
        ctx = ToolContext(cwd=str(Path(cwd).resolve()))
        sess = self._get_or_create_session(session, ctx.cwd)
        await sess.add_user_message(user_message)

        while True:
            response = await self.llm.chat(
                messages=sess.messages,
                tools=self.tools.to_openai_tools(),
            )

            text_content = response.content or ""
            tool_calls = response.tool_calls or []

            await sess.add_message(
                AssistantMessage(content=text_content, tool_calls=tool_calls)
            )

            if not tool_calls:
                return text_content

            await self._execute_tool_calls(tool_calls, ctx, sess)

    async def run_stream(
        self,
        user_message: str,
        cwd: str,
        session: Session | None = None,
    ) -> None:
        ctx = ToolContext(cwd=str(Path(cwd).resolve()))
        sess = self._get_or_create_session(session, ctx.cwd)
        await sess.add_user_message(user_message)

        while True:
            stream = self.llm.chat_stream(
                messages=sess.messages,
                tools=self.tools.to_openai_tools(),
            )

            text, reasoning, tool_calls = await self._build_tool_calls(stream)

            await sess.add_message(AssistantMessage(
                content=text,
                reasoning_content=reasoning,
                tool_calls=tool_calls,
            ))

            if not tool_calls:
                return

            await self._execute_tool_calls(tool_calls, ctx, sess)
