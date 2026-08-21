"""Tool 抽象与公共类型。

接口：name / description / params_schema（JSON Schema）/ timeout_s / run(ctx, **args) -> ToolResult。
"""

from __future__ import annotations

import json
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

MAX_OUTPUT = 8000


def truncate_output(text: str, max_len: int = MAX_OUTPUT) -> tuple[bool, str]:
    """截断工具输出，返回 (是否被截断, 结果文本)。"""
    if len(text) <= max_len:
        return False, text
    return True, text[:max_len] + f"\n…[截断 {len(text) - max_len} 字符]"


class ToolContext(BaseModel):
    """工具执行上下文：工作区（只读共享）、session、附加元数据。"""

    workspace: str | Path = "."
    session_id: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)

    def resolve(self, path: str | Path) -> Path:
        """将相对路径解析到 workspace 内；绝对路径原样返回。"""
        p = Path(path)
        if p.is_absolute():
            return p
        return (Path(self.workspace) / p).resolve()


class ToolResult(BaseModel):
    """工具执行结果（统一含耗时/截断标志）。"""

    ok: bool = True
    output: str = ""
    error: str | None = None
    duration_ms: float = 0.0
    truncated: bool = False

    @property
    def text(self) -> str:
        return self.output if self.ok else (self.error or "")


class Tool(ABC):
    """工具基类。子类需实现 run；name/description/params_schema/timeout_s 通常为类属性。"""

    name: str = ""
    description: str = ""
    params_schema: dict[str, Any] = {}
    timeout_s: float = 0  # 工具超时（秒）；0 = 不限时（经 invoke 调用时强制生效）

    @abstractmethod
    def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
        """执行工具；实现应捕获异常并返回 ToolResult(ok=False)。"""

    def invoke(self, ctx: ToolContext, **args: Any) -> ToolResult:
        """执行工具（含超时）：timeout_s>0 时在独立 daemon 线程运行并限时，超时返回 ToolResult(ok=False)。

        底层异常会重新抛出（由调用方统一转 ToolResult）。
        """
        if not self.timeout_s or self.timeout_s <= 0:
            return self.run(ctx, **args)
        box: dict[str, Any] = {}

        def _target() -> None:
            try:
                box["result"] = self.run(ctx, **args)
            except Exception as exc:  # noqa: BLE001
                box["error"] = exc

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()
        thread.join(timeout=self.timeout_s)
        if thread.is_alive():
            # 超时：不阻塞等待孤儿线程（daemon）；由工具自身负责回收（如 subprocess timeout）
            try:
                args_text = json.dumps(args, ensure_ascii=False)
            except (TypeError, ValueError):
                args_text = repr(args)
            return ToolResult(
                ok=False,
                error=f"工具超时（>{self.timeout_s:g}s）: {self.name} 参数 {args_text}",
                duration_ms=round(self.timeout_s * 1000),
            )
        if "error" in box:
            raise box["error"]
        return box["result"]

    def to_openai_spec(self) -> dict[str, Any]:
        """转为 OpenAI tools 规范（供 LLM 生成参数）。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.params_schema or {"type": "object", "properties": {}},
            },
        }
