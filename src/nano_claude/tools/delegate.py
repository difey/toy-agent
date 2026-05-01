import os
import time
from pathlib import Path

_delegate_counter = 0

from nano_claude.sub_agent import SubAgentCallbacks, SubAgentConfig, SubAgentManager, SubAgentResult
from nano_claude.tool import Tool, ToolContext, ToolExecResult


class DelegateTool(Tool):
    """Tool that delegates sub-tasks to sub-agents for parallel execution."""

    @property
    def name(self) -> str:
        return "delegate"

    @property
    def description(self) -> str:
        return (
            "Delegate one or more independent sub-tasks to sub-agents for parallel execution. "
            "Each sub-agent runs independently. Results are returned together."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "description": "List of sub-tasks to delegate",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": "Unique task identifier, e.g. 'task-1'",
                            },
                            "instruction": {
                                "type": "string",
                                "description": "Detailed instruction for the sub-agent",
                            },
                            "scope": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Files/directories this task is responsible for (hint only)",
                            },
                            "tools": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Tools allowed for this sub-agent (default: all)",
                            },
                        },
                        "required": ["id", "instruction"],
                    },
                },
                "reason": {
                    "type": "string",
                    "description": "Why parallel execution is beneficial here",
                },
            },
            "required": ["tasks", "reason"],
        }

    async def execute(self, args: dict, ctx: ToolContext) -> ToolExecResult:
        tasks = args.get("tasks", [])
        if not tasks:
            return ToolExecResult(output="Error: No tasks provided", title="error")

        # Build SubAgentConfigs
        configs: list[SubAgentConfig] = []
        for task in tasks:
            configs.append(SubAgentConfig(
                id=task["id"],
                instruction=task["instruction"],
                scope=task.get("scope"),
                tools=task.get("tools"),
            ))

        # Get parent agent info
        parent = ctx.parent_agent
        if parent is None:
            return ToolExecResult(
                output="Error: delegate tool requires parent agent context",
                title="error",
            )

        # Build SubAgentCallbacks from the context's on_event callback
        # to stream real-time sub-agent events to the frontend.
        global _delegate_counter
        _delegate_counter += 1
        flow_id = f"delegate_{_delegate_counter}"

        on_event = ctx.on_event
        if on_event is not None:
            async def on_sub_start(aid: str):
                await on_event("sub_agent_start", {"flow_id": flow_id, "agent_id": aid})

            async def on_sub_reasoning(aid: str, text: str):
                await on_event("sub_agent_reasoning", {"flow_id": flow_id, "agent_id": aid, "content": text})

            async def on_sub_tool_start(aid: str, name: str, args: dict):
                await on_event("sub_agent_tool_start", {
                    "flow_id": flow_id, "agent_id": aid, "name": name, "arguments": args,
                })

            async def on_sub_tool_end(aid: str, name: str, title: str, output: str):
                await on_event("sub_agent_tool_end", {
                    "flow_id": flow_id, "agent_id": aid, "name": name, "title": title, "content": output,
                })

            async def on_sub_end(aid: str, text: str):
                await on_event("sub_agent_end", {"flow_id": flow_id, "agent_id": aid, "content": text})

            async def on_sub_error(aid: str, error: str):
                await on_event("sub_agent_error", {"flow_id": flow_id, "agent_id": aid, "content": error})

            sub_callbacks = SubAgentCallbacks(
                on_start=on_sub_start,
                on_reasoning=on_sub_reasoning,
                on_tool_start=on_sub_tool_start,
                on_tool_end=on_sub_tool_end,
                on_end=on_sub_end,
                on_error=on_sub_error,
            )
        else:
            sub_callbacks = None

        manager = SubAgentManager(
            model=parent.llm.model,
            api_key=parent.llm.client.api_key,
            base_url=str(parent.llm.client.base_url or ""),
            full_tools=parent._full_tools,
            permission_callback=ctx.permission_callback,
            ask_user_callback=ctx.ask_user_callback,
            callbacks=sub_callbacks,
            mode=parent.mode,
        )

        results = await manager.run_parallel(configs, ctx.cwd, callbacks=sub_callbacks)

        output = self._format_results(results)
        title = f"delegated {len(results)} tasks"
        return ToolExecResult(output=output, title=title, metadata={"flow_id": flow_id})

    # Max chars per sub-agent output before truncation.
    # Increased from 1000 to 8000 to avoid losing information
    # in analysis-heavy tasks (e.g. reading many files and summarizing).
    MAX_OUTPUT_CHARS = 8000

    def _format_results(self, results: list[SubAgentResult]) -> str:
        lines = ["=== Sub-Agent Results ===\n"]
        for r in results:
            status_icon = {"success": "✓", "error": "✗", "timeout": "⏱"}.get(r.status, "?")
            lines.append(f"[{r.id}] ({status_icon} {r.status})")
            # Summary is always shown in full — never truncate it
            lines.append(f"  Summary: {r.summary or '(no summary)'}")
            if r.files_changed:
                lines.append(f"  Files: {', '.join(r.files_changed)}")
            if r.output:
                if len(r.output) > self.MAX_OUTPUT_CHARS:
                    out = r.output[:self.MAX_OUTPUT_CHARS]
                    out += f"\n  ... (truncated, full output length: {len(r.output)} chars)"
                else:
                    out = r.output
                lines.append(f"  Output: {out}")
            if r.error:
                lines.append(f"  Error: {r.error}")
            lines.append("")
        lines.append("=== All tasks completed ===")
        return "\n".join(lines)
