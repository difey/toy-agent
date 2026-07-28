"""Chat routes — send messages, stream SSE events, respond to permission/question prompts."""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from nano_claude.core.state import state
from nano_claude.interfaces.web.models import ChatRequest
from nano_claude.interfaces.web.services.chat_service import run_chat, sse_event_generator

router = APIRouter()


@router.post("/api/chat")
async def api_chat(req: ChatRequest):
    if state.agent is None:
        raise HTTPException(status_code=400, detail="请先完成配置（模型和 API Key）后再开始对话")

    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    # Add user message to session first (gets proper timestamp)
    await state.session.add_user_message(message)

    # Schedule agent background task
    response_id = await run_chat(state)

    # Return full current state (user message included with timestamp)
    return {
        "response_id": response_id,
        "current": state.current_info(),
    }


@router.post("/api/stop")
async def api_stop():
    """Cancel the current AI response task."""
    if not state._running or state._running_task is None:
        return {"ok": True, "already_stopped": True}
    state._running_task.cancel()
    return {"ok": True}


@router.post("/api/question-answer")
async def api_question_answer(body: dict):
    if state._pending_question is None:
        raise HTTPException(status_code=400, detail="No pending question")
    answer = body.get("answer")
    if answer is None:
        raise HTTPException(status_code=400, detail="Missing 'answer' field")
    if isinstance(answer, str):
        answer = [answer]
    future = state._pending_question["future"]
    if not future.done():
        future.set_result(answer)
    return {"ok": True}


@router.post("/api/permission-response")
async def api_permission_response(body: dict):
    if state._pending_permission is None:
        raise HTTPException(status_code=400, detail="No pending permission request")
    decision = body.get("decision")
    if decision not in ("allow", "deny", "allow_always"):
        raise HTTPException(status_code=400, detail="Decision must be 'allow', 'deny', or 'allow_always'")
    future = state._pending_permission["future"]
    if not future.done():
        future.set_result(decision)
    return {"ok": True}


@router.get("/api/events")
async def api_events(response_id: str = Query(...)):
    queue = state.get_sse_queue(response_id)
    if queue is None:
        raise HTTPException(status_code=404, detail="Response stream not found")

    return StreamingResponse(
        sse_event_generator(state, response_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
