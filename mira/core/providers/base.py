"""LLMProvider 抽象接口与核心数据模型。

统一覆盖：文本补全、流式、工具调用参数（P1 启用 tools）、结构化输出。
"""

from __future__ import annotations

import base64
import mimetypes
from abc import ABC, abstractmethod
from collections.abc import Iterator
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


def _to_image_url(url: str) -> str:
    """图片地址规范化：http(s)/data: 原样返回；本地路径 → base64 data URI。

    OpenAI 兼容端点（如 opencode-go）不接受裸本地路径，须转 data URI。
    """
    if url.startswith("data:") or url.startswith("http://") or url.startswith("https://"):
        return url
    try:
        p = Path(url)
        if p.is_file():
            mime = mimetypes.guess_type(url)[0] or "application/octet-stream"
            b64 = base64.b64encode(p.read_bytes()).decode()
            return f"data:{mime};base64,{b64}"
    except OSError:
        pass
    return url


class ChatRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ChatMessage(BaseModel):
    """对话消息（与 api.protocol.Message 解耦，这里是 provider 视角的输入）。"""

    role: ChatRole
    content: str = ""
    name: str | None = None
    tool_call_id: str | None = None
    reasoning_content: str = ""  # DeepSeek thinking 推理链：多轮历史需原样回传（否则 litellm 注入占位符）
    tool_calls: list[dict[str, Any]] | None = None  # P1 工具调用参数
    images: list[str] = Field(default_factory=list)  # 多模态图片（本地绝对路径或 URL；用户消息用）

    def to_api(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role.value}
        if self.images:
            # OpenAI 多模态 content：文本 + 图片（本地路径自动转 base64 data URI）
            parts: list[dict[str, Any]] = []
            if self.content:
                parts.append({"type": "text", "text": self.content})
            for img in self.images:
                parts.append(
                    {"type": "image_url", "image_url": {"url": _to_image_url(img)}}
                )
            d["content"] = parts
        else:
            d["content"] = self.content
        if self.name:
            d["name"] = self.name
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.reasoning_content:
            d["reasoning_content"] = self.reasoning_content  # DeepSeek thinking 需回传
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        return d


class Usage(BaseModel):
    """用量（基于服务商 usage 响应记账，决策 #6：不做估算）。"""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0  # 成本来自服务商用量响应，无则 0

    @property
    def total(self) -> int:
        return self.total_tokens or (self.input_tokens + self.output_tokens)


class StreamChunk(BaseModel):
    """流式输出的一个增量片段；done=True 的末片携带 usage / finish_reason / tool_calls。"""

    text: str = ""
    reasoning_content: str = ""  # DeepSeek thinking 推理链增量（需累积并保留到历史）
    done: bool = False
    finish_reason: str | None = None
    usage: Usage | None = None
    tool_calls: list[dict[str, Any]] | None = None  # OpenAI 格式工具调用（末片携带）


class ModelResponse(BaseModel):
    """一次非流式（聚合）响应的结果。"""

    content: str = ""
    finish_reason: str | None = None
    usage: Usage = Field(default_factory=Usage)
    tool_calls: list[dict[str, Any]] | None = None


class ModelInfo(BaseModel):
    """Provider 可用模型（含是否支持 thinking 及其 effort 枚举）。"""

    id: str
    name: str = ""
    supports_thinking: bool = False
    thinking_efforts: list[str] = Field(default_factory=list)  # 该模型支持的 effort 值（空=不支持）


class LLMProvider(ABC):
    """LLM 供应商适配器抽象。id 用于路由。"""

    id: str

    @abstractmethod
    def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        effort: str | None = None,
    ) -> Iterator[StreamChunk]:
        """流式补全：产出增量 chunk，末片带 usage / finish_reason / tool_calls。

        effort：reasoning 模型的思考强度（如 low/medium/high）；非 reasoning 模型传 None/off。
        """

    def list_models(self) -> list[ModelInfo]:
        """列出该 provider 可用模型（含 thinking 能力）。默认空；子类按需实现。"""
        return []
    def chat(
        self,
        messages: list[ChatMessage],
        **kwargs: Any,
    ) -> ModelResponse:
        """非流式补全：聚合 stream_chat 的结果。"""
        buf: list[str] = []
        usage = Usage()
        finish: str | None = None
        tool_calls: list[dict[str, Any]] | None = None
        for chunk in self.stream_chat(messages, **kwargs):
            buf.append(chunk.text)
            if chunk.usage:
                usage = chunk.usage
            if chunk.tool_calls:
                tool_calls = chunk.tool_calls
            if chunk.done:
                finish = chunk.finish_reason or finish
        return ModelResponse(
            content="".join(buf),
            finish_reason=finish,
            usage=usage,
            tool_calls=tool_calls,
        )
