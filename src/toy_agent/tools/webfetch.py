import base64

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify

from toy_agent.tool import Tool, ToolContext, ToolExecResult

MAX_SIZE = 5 * 1024 * 1024
DEFAULT_TIMEOUT = 30.0
MAX_TIMEOUT = 120.0

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/143.0.0.0 Safari/537.36"
)

ACCEPT_HEADERS = {
    "markdown": (
        "text/markdown;q=1.0, text/x-markdown;q=0.9, "
        "text/plain;q=0.8, text/html;q=0.7, */*;q=0.1"
    ),
    "text": (
        "text/plain;q=1.0, text/markdown;q=0.9, "
        "text/html;q=0.8, */*;q=0.1"
    ),
    "html": (
        "text/html;q=1.0, application/xhtml+xml;q=0.9, "
        "text/plain;q=0.8, */*;q=0.1"
    ),
}


class WebFetchTool(Tool):
    @property
    def name(self) -> str:
        return "webfetch"

    @property
    def description(self) -> str:
        return (
            "Fetches content from a specified URL. "
            "Takes a URL and optional format as input. "
            "Converts HTML to markdown by default. "
            "HTTP URLs are automatically upgraded to HTTPS. "
            "Format options: markdown (default), text, or html. "
            "Results may be summarized if the content is very large."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch content from",
                },
                "format": {
                    "type": "string",
                    "enum": ["text", "markdown", "html"],
                    "description": "The format to return the content in",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (max 120)",
                },
            },
            "required": ["url"],
        }

    async def execute(self, args: dict, ctx: ToolContext) -> ToolExecResult:
        url = args["url"]
        fmt = args.get("format", "markdown")
        timeout = min(args.get("timeout", DEFAULT_TIMEOUT), MAX_TIMEOUT)

        if not url.startswith("http://") and not url.startswith("https://"):
            return ToolExecResult(
                output=f"Error: URL must start with http:// or https://: {url}",
                title="webfetch [error]",
            )

        if url.startswith("http://"):
            url = "https://" + url[7:]

        headers = {
            "User-Agent": UA,
            "Accept": ACCEPT_HEADERS.get(fmt, ACCEPT_HEADERS["markdown"]),
            "Accept-Language": "en-US,en;q=0.9",
        }

        try:
            async with httpx.AsyncClient(timeout=float(timeout)) as client:
                response = await client.get(url, headers=headers)

                if (
                    response.status_code == 403
                    and response.headers.get("cf-mitigated") == "challenge"
                ):
                    headers["User-Agent"] = "toy-agent"
                    response = await client.get(url, headers=headers)

                response.raise_for_status()

                content = response.content
                if len(content) > MAX_SIZE:
                    return ToolExecResult(
                        output=f"Error: response exceeds 5MB limit ({len(content)} bytes)",
                        title="webfetch [error]",
                    )

                content_type = response.headers.get("content-type", "")
                mime = content_type.split(";")[0].strip().lower()

                if mime.startswith("image/"):
                    b64 = base64.b64encode(content).decode()
                    return ToolExecResult(
                        output=f"Image fetched: {mime} ({len(content)} bytes)\n"
                               f"data:{mime};base64,{b64[:200]}...",
                        title=f"webfetch [{url[:50]}]",
                    )

                text = content.decode("utf-8", errors="replace")

                if fmt == "markdown" and "text/html" in content_type:
                    text = markdownify(text, heading_style="ATX", bullets="-")
                elif fmt == "text" and "text/html" in content_type:
                    soup = BeautifulSoup(text, "html.parser")
                    for tag in soup(["script", "style", "noscript", "iframe", "object", "embed"]):
                        tag.decompose()
                    text = soup.get_text(separator="\n", strip=True)

                return ToolExecResult(
                    output=text,
                    title=f"webfetch [{url[:50]}]",
                )

        except httpx.TimeoutException:
            return ToolExecResult(
                output=f"Timeout fetching URL after {timeout}s: {url}",
                title="webfetch [timeout]",
            )
        except httpx.HTTPStatusError as e:
            return ToolExecResult(
                output=f"HTTP error fetching URL: {e.response.status_code} - {url}",
                title="webfetch [error]",
            )
        except Exception as e:
            return ToolExecResult(
                output=f"Error fetching URL: {e}",
                title="webfetch [error]",
            )
