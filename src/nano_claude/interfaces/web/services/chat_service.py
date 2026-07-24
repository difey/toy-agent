"""Chat orchestration service — wires the core Agent to web SSE events."""

import asyncio
import json
import os
import traceback

from fastapi import HTTPException

from nano_claude.core.message import ToolCall, UserMessage
from nano_claude.infra.session import save_current

from nano_claude.interfaces.web.state import WebAppState

from nano_claude.interfaces.web.services.diff_service import (
    take_snapshot, detect_file_changes, save_checkpoint, cleanup_checkpoints,
    _get_git_head_hash,
)


async def run_chat(state: WebAppState, message: str) -> str:
    """Schedule the agent to run in background. Returns the response_id immediately."""
    if state._running:
        raise HTTPException(status_code=409, detail="已有正在运行的回复，请先停止当前回复")

    session = state.session

    state._running = True

    response_id = f"chat_{id(session)}_{len(session.messages)}_{id(message)}"
    state.create_sse_queue(response_id)

    # Run the agent in a background task so the response_id is returned immediately
    task = asyncio.ensure_future(_execute_chat(state, message, response_id))
    state._running_task = task
    return response_id


async def _execute_chat(state: WebAppState, message: str, response_id: str) -> None:
    """Actually execute the agent chat in the background, pushing SSE events."""
    agent = state.agent
    session = state.session
    cwd = state.cwd

    # Set up agent callbacks to push events
    original_on_text = agent.on_text_delta
    original_on_tool_start = agent.on_tool_start
    original_on_tool_end = agent.on_tool_end
    original_permission = agent.permission_callback
    original_ask_user = agent.ask_user_callback
    original_on_event = agent.on_event_callback

    async def on_text(text: str):
        await state.push_event("message", {"role": "assistant", "type": "text", "content": text})
        if original_on_text:
            result = original_on_text(text)
            if asyncio.iscoroutine(result):
                await result

    async def on_tool_start(call: ToolCall):
        await state.push_event("message", {
            "role": "assistant",
            "type": "tool_start",
            "name": call.name,
            "arguments": call.arguments,
        })
        if original_on_tool_start:
            result = original_on_tool_start(call)
            if asyncio.iscoroutine(result):
                await result

    async def on_tool_end(name: str, title: str, output: str, metadata: dict | None = None):
        event_data = {
            "role": "tool",
            "type": "tool_result",
            "name": name,
            "title": title,
            "content": output,
        }
        # Pass through flow_id from delegate tool for frontend toggle matching
        if metadata and "flow_id" in metadata:
            event_data["flow_id"] = metadata["flow_id"]
        await state.push_event("message", event_data)
        if original_on_tool_end:
            result = original_on_tool_end(name, title, output, metadata)
            if asyncio.iscoroutine(result):
                await result

    async def permission_callback(tool: str, target: str, resolved_path: str) -> str:
        """Ask the user for permission to access a file outside cwd.

        Pushes a 'permission_request' SSE event to the frontend and waits
        for the user's decision (allow / deny / allow_always).
        """
        await state.push_event("permission_request", {
            "tool": tool,
            "target": target,
            "resolved_path": resolved_path,
            "cwd": cwd,
        })
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        state._pending_permission = {
            "future": future,
            "tool": tool,
            "target": target,
            "resolved_path": resolved_path,
        }
        try:
            result = await asyncio.wait_for(future, timeout=120)
            return result
        except asyncio.TimeoutError:
            return "deny"
        finally:
            state._pending_permission = None

    async def ask_user_callback(header: str, question: str, options: list[dict], multiple: bool) -> list[str]:
        await state.push_event("question", {
            "header": header,
            "question": question,
            "options": options,
            "multiple": multiple,
        })
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        state._pending_question = {
            "future": future,
            "header": header,
            "question": question,
            "options": options,
            "multiple": multiple,
        }
        try:
            result = await asyncio.wait_for(future, timeout=300)
            return result
        except asyncio.TimeoutError:
            return ["(skipped)"]
        finally:
            state._pending_question = None

    async def on_event(event_type: str, data: dict):
        """Push sub-agent real-time events as SSE sub_agent_message events."""
        await state.push_event("sub_agent_message", {
            "flow_id": data.get("flow_id", ""),
            "agent_id": data.get("agent_id", ""),
            "type": event_type.replace("sub_agent_", ""),
            "name": data.get("name", ""),
            "arguments": data.get("arguments", {}),
            "content": data.get("content", ""),
            "title": data.get("title", ""),
        })

    agent.on_text_delta = on_text
    agent.on_tool_start = on_tool_start
    agent.on_tool_end = on_tool_end
    agent.permission_callback = permission_callback
    agent.ask_user_callback = ask_user_callback
    agent.on_event_callback = on_event

    try:
        # Take snapshot before agent runs to detect file changes
        before_snapshot, before_content, before_binary = take_snapshot(cwd)
        user_msg_count = sum(1 for m in session.messages if isinstance(m, UserMessage))
        segment_key = f"seg-{user_msg_count}"

        await agent.run_stream(message, cwd, session=session)

        # Take snapshot after agent runs and detect changes
        after_snapshot, _after_content, after_binary = take_snapshot(cwd)
        binary_set = before_binary | after_binary
        changed_files = detect_file_changes(
            before_snapshot, after_snapshot,
            cwd=cwd, before_content=before_content, binary_set=binary_set,
        )

        if changed_files["files_changed"] > 0:
            git_hash = _get_git_head_hash(cwd)
            checkpoint_filename = save_checkpoint(
                cwd, changed_files, segment_key,
                os.path.basename(state.session_file_ref[0]),
                git_hash,
            )
            # Build simplified file list for the frontend
            files_list = []
            for rel_path in changed_files.get("modified", {}):
                files_list.append({"path": rel_path, "status": "modified"})
            for rel_path in changed_files.get("deleted", {}):
                files_list.append({"path": rel_path, "status": "deleted"})
            for rel_path in changed_files.get("added", []):
                files_list.append({"path": rel_path, "status": "added"})
            for rel_path in changed_files.get("binary", []):
                files_list.append({"path": rel_path, "status": "binary"})

            await state.push_event("diff_summary", {
                "segment_key": segment_key,
                "checkpoint_filename": checkpoint_filename,
                "summary": {
                    "files_changed": changed_files["files_changed"],
                    "files": files_list,
                },
            })

        # Cleanup old checkpoints
        cleanup_checkpoints(cwd)

        await state.push_event("done", {})
    except asyncio.CancelledError:
        await state.push_event("done", {})
    except Exception:
        tb = traceback.format_exc()
        await state.push_event("error", {"message": tb})
    finally:
        agent.on_text_delta = original_on_text
        agent.on_tool_start = original_on_tool_start
        agent.on_tool_end = original_on_tool_end
        agent.permission_callback = original_permission
        agent.ask_user_callback = original_ask_user
        agent.on_event_callback = original_on_event
        save_current(session, state.session_file_ref[0])
        state._running = False
        state._running_task = None


async def sse_event_generator(state: WebAppState, response_id: str):
    """Async generator that yields SSE-formatted events from the queue."""
    queue = state.get_sse_queue(response_id)
    if queue is None:
        yield f"event: error\ndata: {json.dumps({'message': 'Response stream not found'})}\n\n"
        return

    try:
        while True:
            event, data = await queue.get()
            payload = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            yield payload
            if event == "done" or event == "error":
                break
    except (asyncio.CancelledError, GeneratorExit):
        pass
    finally:
        state.remove_sse_queue(response_id)
