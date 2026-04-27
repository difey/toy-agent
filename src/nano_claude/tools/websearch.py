from datetime import datetime

from nano_claude.tool import Tool, ToolContext, ToolExecResult
from nano_claude.tools.exa_client import call_exa_tool


class WebSearchTool(Tool):
    @property
    def name(self) -> str:
        return "websearch"

    @property
    def description(self) -> str:
        return (
            "Search the web using Exa AI - performs real-time web searches. "
            "Provides up-to-date information for current events and recent data. "
            "Supports configurable result counts and returns the content from "
            "the most relevant websites. "
            "Use this tool for accessing information beyond your knowledge cutoff. "
            f"The current year is {datetime.now().year}. "
            "You MUST use this year when searching for recent information."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query",
                },
                "numResults": {
                    "type": "integer",
                    "description": "Number of results to return (default: 8)",
                },
                "livecrawl": {
                    "type": "string",
                    "enum": ["fallback", "preferred"],
                    "description": "Live crawling mode: fallback or preferred",
                },
                "type": {
                    "type": "string",
                    "enum": ["auto", "fast", "deep"],
                    "description": "Search type: auto, fast, or deep",
                },
                "contextMaxCharacters": {
                    "type": "integer",
                    "description": "Max characters for context (default: 10000)",
                },
            },
            "required": ["query"],
        }

    async def execute(self, args: dict, ctx: ToolContext) -> ToolExecResult:
        query = args["query"]
        exa_args = {
            "query": query,
            "type": args.get("type", "auto"),
            "numResults": args.get("numResults", 8),
            "livecrawl": args.get("livecrawl", "fallback"),
            "contextMaxCharacters": args.get("contextMaxCharacters", 10000),
        }

        try:
            result = await call_exa_tool("web_search_exa", exa_args)
        except Exception as e:
            return ToolExecResult(
                output=f"Web search failed: {e}",
                title="websearch [error]",
            )

        if not result:
            return ToolExecResult(
                output="No search results found.",
                title=f"websearch [{query[:40]}]",
            )

        return ToolExecResult(
            output=result,
            title=f"websearch [{query[:40]}]",
        )
