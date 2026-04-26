import json
import os

import httpx

EXA_URL = "https://mcp.exa.ai/mcp"
if api_key := os.environ.get("EXA_API_KEY"):
    EXA_URL += f"?exaApiKey={api_key}"


async def call_exa_tool(tool_name: str, args: dict, timeout: float = 25.0) -> str | None:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": args,
        },
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            EXA_URL,
            json=payload,
            headers={"Accept": "application/json, text/event-stream"},
        )
        response.raise_for_status()

        for line in response.text.split("\n"):
            if not line.startswith("data: "):
                continue
            try:
                data = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            contents = data.get("result", {}).get("content", [])
            if contents and "text" in contents[0]:
                return contents[0]["text"]

    return None
