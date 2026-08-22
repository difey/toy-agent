"""attach_image：把一张图片加入 runtime history（多模态 USER 消息），供视觉模型在下一轮查看。

设计要点：
- 工具**不读取/解码**图片本身，只把路径交给 runtime 的待注入队列（`_attach_image` 钩子）；
- runtime 在下一轮 `_llm_call` 发送请求前，把待注入图片作为多模态 USER 消息追加到
  messages 末尾（在 TOOL 结果之后）——不插入 assistant(tool_calls) 与 TOOL 结果之间，
  从而不破坏 DeepSeek 的 tool_call 完整性约束；
- 面向视觉 agent（vision）：主 agent 是纯文本模型，无需/不应启用本工具。
"""

from __future__ import annotations

from typing import Any

from mira.core.tools.base import Tool, ToolContext, ToolResult

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


class AttachImageTool(Tool):
    name = "attach_image"
    description = (
        "把一张图片（本地绝对路径）加入当前对话上下文，使具备视觉能力的模型在下一轮能"
        "查看该图片并回答相关问题。调用后请在下一轮回复中描述/分析图片。"
        "仅支持图片文件（png/jpg/jpeg/webp/gif/bmp）。"
    )
    params_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "图片文件的绝对路径"},
        },
        "required": ["path"],
    }

    def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
        raw = str(args.get("path") or "").strip()
        if not raw:
            return ToolResult(ok=False, error="attach_image 需要 path 参数（图片绝对路径）")
        p = ctx.resolve(raw)
        if not p.is_file():
            return ToolResult(ok=False, error=f"文件不存在: {p}")
        ext = p.suffix.lower()
        if ext not in _IMAGE_EXTS:
            return ToolResult(ok=False, error=f"不支持的图片格式: {ext or '（无扩展名）'}（支持 {sorted(_IMAGE_EXTS)}）")
        attach = (ctx.meta or {}).get("attach_image")
        if attach is None:
            return ToolResult(ok=False, error="attach_image 需在运行时会话中执行（缺少 attach_image 钩子）")
        try:
            attach(str(p))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, error=f"加入图片失败: {exc}")
        return ToolResult(ok=True, output=f"图片已加入上下文（下一轮可查看）: {p}")
