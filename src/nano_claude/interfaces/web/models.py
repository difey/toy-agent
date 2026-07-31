"""Pydantic request/response models for the Web UI API."""

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    # 回复过程中的额外说明：携带当前正在运行的 response_id。
    # 为空时表示发起一轮新对话。
    response_id: str | None = None


class SessionInfo(BaseModel):
    path: str
    name: str
    title: str
    messages: int
    tokens: int
    preview: str
    index: int = 0
    is_current: bool = False


class CurrentInfo(BaseModel):
    path: str
    name: str
    title: str
    messages: int
    tokens: int
    preview: str
    is_current: bool = True
    index: int = 1
    message_list: list[dict] = []


class ApiResponse(BaseModel):
    ok: bool = True
    error: str | None = None


class SetupRequest(BaseModel):
    model: str
    api_key: str | None = None
