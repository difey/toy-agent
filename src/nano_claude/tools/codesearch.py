from nano_claude.tool import Tool, ToolContext, ToolExecResult
from nano_claude.tools.exa_client import call_exa_tool


class CodeSearchTool(Tool):
    @property
    def name(self) -> str:
        return "codesearch"

    @property
    def description(self) -> str:
        return (
            "Search and get relevant context for any programming task using Exa Code API. "
            "Provides the highest quality and freshest context for libraries, SDKs, and APIs. "
            "Use this tool for ANY question or task related to programming. "
            "Returns comprehensive code examples, documentation, and API references. "
            "Adjustable token count (1000-50000) for focused or comprehensive results. "
            "Default 5000 tokens provides balanced context for most queries. "
            "Examples: React useState hook examples, Python pandas dataframe filtering."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The programming-related search query",
                },
                "tokensNum": {
                    "type": "integer",
                    "description": "Number of tokens to return (1000-50000, default: 5000)",
                },
            },
            "required": ["query"],
        }

    async def execute(self, args: dict, ctx: ToolContext) -> ToolExecResult:
        query = args["query"]
        exa_args = {
            "query": query,
            "tokensNum": args.get("tokensNum", 5000),
        }

        try:
            result = await call_exa_tool("get_code_context_exa", exa_args)
        except Exception as e:
            return ToolExecResult(
                output=f"Code search failed: {e}",
                title="codesearch [error]",
            )

        if not result:
            return ToolExecResult(
                output="No code documentation found.",
                title=f"codesearch [{query[:40]}]",
            )

        return ToolExecResult(
            output=result,
            title=f"codesearch [{query[:40]}]",
        )
