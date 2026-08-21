"""内建工具：web_fetch — 抓取 URL 内容（HTML 转文本）。

补齐 Mira 既有的 `web_fetch` 候选工具。参考 nano_claude.tools.webfetch；
HTML→文本用 stdlib HTMLParser（不引入 bs4/markdownify 依赖）。
"""

from __future__ import annotations

import time
from html.parser import HTMLParser
from typing import Any

import httpx

from mira.core.tools.base import Tool, ToolContext, ToolResult, truncate_output

MAX_SIZE = 5 * 1024 * 1024
DEFAULT_TIMEOUT = 30.0
MAX_TIMEOUT = 120.0

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/143.0.0.0 Safari/537.36"
)

_STRIP_TAGS = {"script", "style", "noscript", "iframe", "object", "embed"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs) -> None:  # noqa: ANN001
        if tag in _STRIP_TAGS:
            self._skip += 1
        if tag in ("p", "div", "li", "h1", "h2", "h3", "h4", "tr", "br", "pre"):
            self.parts.append("\n")

    def handle_endtag(self, tag) -> None:  # noqa: ANN001
        if tag in _STRIP_TAGS and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def _html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    lines = [ln.strip() for ln in "".join(parser.parts).split("\n")]
    return "\n".join(ln for ln in lines if ln)


class WebFetchTool(Tool):
    name = "web_fetch"
    description = (
        "抓取指定 URL 的内容，默认把 HTML 转为纯文本（format: text/markdown/html）。"
        "HTTP 自动升级为 HTTPS。结果过大时会截断。"
    )
    params_schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "要抓取的 URL"},
            "format": {
                "type": "string",
                "enum": ["text", "markdown", "html"],
                "description": "返回格式（默认 text；markdown 暂同 text）",
            },
            "timeout": {"type": "integer", "description": "超时秒数（最大 120）"},
        },
        "required": ["url"],
    }

    def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
        url = args.get("url", "")
        if not url:
            return ToolResult(ok=False, error="缺少 url 参数")
        fmt = args.get("format", "text")
        timeout = min(float(args.get("timeout") or DEFAULT_TIMEOUT), MAX_TIMEOUT)

        if not url.startswith(("http://", "https://")):
            return ToolResult(ok=False, error=f"URL 必须以 http(s):// 开头: {url}")
        if url.startswith("http://"):
            url = "https://" + url[7:]

        headers = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
        t0 = time.perf_counter()
        try:
            resp = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
            resp.raise_for_status()
            content = resp.content
            if len(content) > MAX_SIZE:
                return ToolResult(ok=False, error=f"响应超过 5MB 限制（{len(content)} 字节）")
            text = content.decode("utf-8", errors="replace")
            if "text/html" in resp.headers.get("content-type", "") and fmt != "html":
                text = _html_to_text(text)
            truncated, output = truncate_output(text.strip())
            return ToolResult(
                ok=True,
                output=output,
                truncated=truncated,
                duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
        except httpx.TimeoutException:
            return ToolResult(
                ok=False,
                error=f"抓取超时（>{timeout:g}s）: {url}",
                duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
        except httpx.HTTPStatusError as exc:
            return ToolResult(
                ok=False,
                error=f"HTTP {exc.response.status_code}: {url}",
                duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                ok=False,
                error=f"抓取失败: {exc}",
                duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
