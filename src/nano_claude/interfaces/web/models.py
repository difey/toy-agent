"""Pydantic request/response models for the Web UI API."""

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str


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
