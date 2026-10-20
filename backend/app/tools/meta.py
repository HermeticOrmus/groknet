"""Two tools whose names never change, so a bot can reach new Groknet tools
without re-adding the MCP server.

Grok Bot caches the tool list when the server is added and only re-discovers on a
manual refresh. Any tool shipped later is still reachable through
`call_groknet_tool`, and `list_groknet_tools` shows what exists right now.
"""

from typing import Any

from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import TextContent

from app.errors import GroknetError
from app.mcp_server import groknet_tool, mcp


@groknet_tool
async def list_groknet_tools() -> dict[str, Any]:
    """List every Groknet tool available right now, with its description and input schema.

    Call this when a Groknet capability seems missing from your tool list: Groknet
    adds tools over time and your connector may hold an older list. Any tool shown
    here can be invoked through call_groknet_tool without reconnecting.
    """
    tools = await mcp.list_tools()
    return {
        "tools": [
            {"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
            for t in tools
        ]
    }


@groknet_tool
async def call_groknet_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Invoke any Groknet tool by name, including ones added after you connected.

    name: a tool name from list_groknet_tools. arguments: that tool's arguments as an
    object, e.g. {"groknet_token": "...", "handle": "juan"}. Returns {"tool": name,
    "result": <that tool's result>}.
    """
    tool = mcp._tool_manager.get_tool(name)
    if tool is None or name in {"call_groknet_tool", "list_groknet_tools"}:
        raise GroknetError(
            f"Unknown Groknet tool {name!r}. Call list_groknet_tools to see what is available."
        )
    try:
        result = await tool.run(arguments or {}, context=None, convert_result=False)
    except ToolError as e:
        # The inner tool's message, minus the SDK's "Error executing tool <name>: " prefix.
        raise GroknetError(str(e).split(": ", 1)[-1]) from e
    if isinstance(result, list) and result and all(isinstance(c, TextContent) for c in result):
        result = "\n".join(c.text for c in result)
    return {"tool": name, "result": result}
