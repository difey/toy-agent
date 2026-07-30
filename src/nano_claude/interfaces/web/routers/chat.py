"""Chat routes — send messages, stream SSE events, respond to permission/question prompts."""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from nano_claude.core.state import state
from nano_claude.interfaces.web.models import ChatRequest

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
    try:
        response_id = await state.run_chat()
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))

    # Return full current state (user message included with timestamp)
    return {
        "response_id": response_id,
        "current": state.current_info(),
    }


@router.post("/api/stop")
async def api_stop():
    """Cancel the current AI response task."""
    already_stopped = not state.stop_running()
    return {"ok": True, "already_stopped": already_stopped}


@router.post("/api/question-answer")
async def api_question_answer(body: dict):
    answer = body.get("answer")
    if answer is None:
        raise HTTPException(status_code=400, detail="Missing 'answer' field")
    try:
        state.respond_question(answer)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@router.post("/api/permission-response")
async def api_permission_response(body: dict):
    decision = body.get("decision")
    if not decision:
        raise HTTPException(status_code=400, detail="Missing 'decision' field")
    try:
        state.respond_permission(decision)
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@router.get("/api/events")
async def api_events(response_id: str = Query(...)):
    queue = state.get_sse_queue(response_id)
    if queue is None:
        raise HTTPException(status_code=404, detail="Response stream not found")

    return StreamingResponse(
        state.sse_event_generator(response_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
